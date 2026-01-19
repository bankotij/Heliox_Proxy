"""Gateway router - matches requests to routes and handles authentication."""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import ApiKey, BlockRule, CachePolicy, Route, Tenant
from src.models.api_key import ApiKeyStatus
from src.services.abuse import AbuseCheckResult, abuse_detector
from src.services.rate_limiter import (
    RateLimitResult,
    quota_manager,
    rate_limit_metrics,
    token_bucket,
)

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


@dataclass
class AuthResult:
    """Result of API key authentication."""

    authenticated: bool
    api_key: ApiKey | None = None
    tenant: Tenant | None = None
    error: str | None = None
    error_code: str | None = None


@dataclass
class RouteMatch:
    """Result of route matching."""

    matched: bool
    route: Route | None = None
    policy: CachePolicy | None = None
    path_remainder: str = ""
    error: str | None = None


@dataclass
class GatewayContext:
    """Full context for a gateway request."""

    auth: AuthResult
    route_match: RouteMatch
    rate_limit: RateLimitResult | None = None
    abuse_check: AbuseCheckResult | None = None
    quota_allowed: bool = True
    quota_error: str | None = None


class GatewayRouter:
    """
    Handles request routing, authentication, and authorization.
    
    Responsibilities:
    - Authenticate API key from X-API-Key header
    - Match request path to configured routes
    - Apply rate limiting and quota checks
    - Check abuse status
    """

    API_KEY_HEADER = "X-API-Key"

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._route_cache: dict[str, Route] = {}

    async def process_request(
        self,
        route_name: str,
        path: str,
        method: str,
        api_key_header: str | None,
    ) -> GatewayContext:
        """
        Process a gateway request through all checks.
        
        Args:
            route_name: Name of the route from URL
            path: Path after route name
            method: HTTP method
            api_key_header: Value of X-API-Key header
        
        Returns:
            GatewayContext with all check results
        """
        # Step 1: Authenticate API key
        auth = await self.authenticate(api_key_header)
        if not auth.authenticated:
            return GatewayContext(
                auth=auth,
                route_match=RouteMatch(matched=False),
            )

        # Step 2: Match route
        route_match = await self.match_route(
            route_name,
            method,
            auth.tenant.id if auth.tenant else None,
        )
        if not route_match.matched:
            return GatewayContext(auth=auth, route_match=route_match)

        # Step 3: Check abuse status
        abuse_check = await abuse_detector.check_abuse(auth.api_key.id)
        if abuse_check.is_blocked:
            return GatewayContext(
                auth=auth,
                route_match=route_match,
                abuse_check=abuse_check,
            )

        # Step 4: Apply rate limiting
        rate_key = f"{auth.api_key.id}:{route_match.route.id}"
        rate = self._get_rate_limit(auth.api_key, route_match.route)
        burst = self._get_burst_limit(auth.api_key, route_match.route)

        # Apply abuse multiplier if soft-limited
        if abuse_check.is_soft_limited:
            rate *= abuse_check.rate_multiplier
            burst = int(burst * abuse_check.rate_multiplier)

        rate_limit = await token_bucket.is_allowed(rate_key, rate, burst)
        if not rate_limit.allowed:
            rate_limit_metrics.record_denied()
            return GatewayContext(
                auth=auth,
                route_match=route_match,
                rate_limit=rate_limit,
                abuse_check=abuse_check,
            )

        rate_limit_metrics.record_allowed()

        # Step 5: Check quotas
        quota_allowed, quota_error = await quota_manager.check_and_increment(
            auth.api_key.id,
            auth.api_key.quota_daily,
            auth.api_key.quota_monthly,
        )
        if not quota_allowed:
            rate_limit_metrics.record_quota_exceeded()

        return GatewayContext(
            auth=auth,
            route_match=route_match,
            rate_limit=rate_limit,
            abuse_check=abuse_check,
            quota_allowed=quota_allowed,
            quota_error=quota_error,
        )

    async def authenticate(self, api_key_header: str | None) -> AuthResult:
        """
        Authenticate request using API key.
        
        Args:
            api_key_header: Value of X-API-Key header
        
        Returns:
            AuthResult with authentication status
        """
        if not api_key_header:
            return AuthResult(
                authenticated=False,
                error="Missing API key",
                error_code="missing_api_key",
            )

        # Look up API key
        query = (
            select(ApiKey)
            .options(selectinload(ApiKey.tenant))
            .where(ApiKey.key == api_key_header)
        )
        result = await self._db.execute(query)
        api_key = result.scalar_one_or_none()

        if not api_key:
            logger.warning("Invalid API key attempted", key_prefix=api_key_header[:10])
            return AuthResult(
                authenticated=False,
                error="Invalid API key",
                error_code="invalid_api_key",
            )

        # Check key status
        if api_key.status != ApiKeyStatus.ACTIVE:
            return AuthResult(
                authenticated=False,
                error=f"API key is {api_key.status}",
                error_code="key_inactive",
            )

        # Check expiration
        if api_key.expires_at:
            if api_key.expires_at < datetime.now(timezone.utc):
                return AuthResult(
                    authenticated=False,
                    error="API key has expired",
                    error_code="key_expired",
                )

        # Check tenant status
        if not api_key.tenant.is_active:
            return AuthResult(
                authenticated=False,
                error="Tenant is inactive",
                error_code="tenant_inactive",
            )

        # Check for active blocks
        block_query = (
            select(BlockRule)
            .where(BlockRule.api_key_id == api_key.id)
            .where(BlockRule.unblocked_at.is_(None))
            .where(
                (BlockRule.blocked_until.is_(None)) |
                (BlockRule.blocked_until > datetime.now(timezone.utc))
            )
        )
        block_result = await self._db.execute(block_query)
        active_block = block_result.scalar_one_or_none()

        if active_block:
            return AuthResult(
                authenticated=False,
                error=f"API key is blocked: {active_block.reason}",
                error_code="key_blocked",
            )

        # Update last used timestamp
        api_key.last_used_at = datetime.now(timezone.utc)

        return AuthResult(
            authenticated=True,
            api_key=api_key,
            tenant=api_key.tenant,
        )

    async def match_route(
        self,
        route_name: str,
        method: str,
        tenant_id: str | None,
    ) -> RouteMatch:
        """
        Match a request to a configured route.
        
        Routes are matched by:
        1. Route name (exact match)
        2. HTTP method
        3. Tenant (tenant-specific routes take priority over shared)
        
        Args:
            route_name: Name from URL path
            method: HTTP method
            tenant_id: Authenticated tenant ID
        
        Returns:
            RouteMatch with matched route or error
        """
        # Query for routes matching the name
        query = (
            select(Route)
            .options(selectinload(Route.policy))
            .where(Route.name == route_name)
            .where(Route.is_active.is_(True))
            .order_by(Route.priority.desc())
        )
        result = await self._db.execute(query)
        routes = result.scalars().all()

        if not routes:
            return RouteMatch(
                matched=False,
                error=f"Route '{route_name}' not found",
            )

        # Find best match (tenant-specific > shared)
        matched_route: Route | None = None

        for route in routes:
            # Check method
            if not route.matches_method(method):
                continue

            # Prefer tenant-specific route
            if route.tenant_id == tenant_id:
                matched_route = route
                break

            # Fall back to shared route
            if route.tenant_id is None and matched_route is None:
                matched_route = route

        if not matched_route:
            return RouteMatch(
                matched=False,
                error=f"Route '{route_name}' does not support method {method}",
            )

        return RouteMatch(
            matched=True,
            route=matched_route,
            policy=matched_route.policy,
        )

    def _get_rate_limit(self, api_key: ApiKey, route: Route) -> float:
        """Get effective rate limit (key override > route > default)."""
        from src.config import get_settings

        settings = get_settings()

        if api_key.rate_limit_rps is not None:
            return api_key.rate_limit_rps
        if route.rate_limit_rps is not None:
            return route.rate_limit_rps
        return settings.default_rate_limit_rps

    def _get_burst_limit(self, api_key: ApiKey, route: Route) -> int:
        """Get effective burst limit (key override > route > default)."""
        from src.config import get_settings

        settings = get_settings()

        if api_key.rate_limit_burst is not None:
            return api_key.rate_limit_burst
        if route.rate_limit_burst is not None:
            return route.rate_limit_burst
        return settings.default_rate_limit_burst


async def get_gateway_router(db: AsyncSession) -> GatewayRouter:
    """Dependency to get gateway router."""
    return GatewayRouter(db)
