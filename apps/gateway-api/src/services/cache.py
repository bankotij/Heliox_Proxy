"""
Cache service with TTL, SWR (Stale-While-Revalidate), and stampede protection.

This module provides a production-grade caching layer with:
- TTL-based expiration
- Stale-while-revalidate for improved latency
- Stampede protection via distributed locks
- Request coalescing for identical in-flight requests
- Cache key canonicalization
"""

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import parse_qs, urlencode

import structlog

from src.services.redis_client import RedisClient, redis_client

logger = structlog.get_logger(__name__)


class CacheEntryStatus(str, Enum):
    """Status of a cache entry."""

    FRESH = "fresh"
    STALE = "stale"
    MISS = "miss"


@dataclass
class CacheEntry:
    """Represents a cached response."""

    status_code: int
    headers: dict[str, str]
    body: bytes
    created_at: float
    ttl_seconds: int
    stale_seconds: int
    vary_key: str = ""

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps({
            "status_code": self.status_code,
            "headers": self.headers,
            "body": self.body.decode("utf-8", errors="replace"),
            "created_at": self.created_at,
            "ttl_seconds": self.ttl_seconds,
            "stale_seconds": self.stale_seconds,
            "vary_key": self.vary_key,
        })

    @classmethod
    def from_json(cls, data: str) -> "CacheEntry":
        """Deserialize from JSON string."""
        parsed = json.loads(data)
        return cls(
            status_code=parsed["status_code"],
            headers=parsed["headers"],
            body=parsed["body"].encode("utf-8"),
            created_at=parsed["created_at"],
            ttl_seconds=parsed["ttl_seconds"],
            stale_seconds=parsed["stale_seconds"],
            vary_key=parsed.get("vary_key", ""),
        )

    def get_status(self) -> CacheEntryStatus:
        """Determine if the entry is fresh, stale, or expired."""
        age = time.time() - self.created_at
        if age <= self.ttl_seconds:
            return CacheEntryStatus.FRESH
        elif age <= self.ttl_seconds + self.stale_seconds:
            return CacheEntryStatus.STALE
        return CacheEntryStatus.MISS

    @property
    def age_seconds(self) -> float:
        """Get the age of this cache entry."""
        return time.time() - self.created_at


@dataclass
class CacheResult:
    """Result of a cache lookup."""

    status: CacheEntryStatus
    entry: CacheEntry | None = None
    needs_refresh: bool = False


class CacheKeyBuilder:
    """
    Builds canonical cache keys from request parameters.
    
    Ensures consistent cache keys by:
    - Normalizing query parameter order
    - Including selected vary headers
    - Hashing for fixed-length keys
    """

    @staticmethod
    def build(
        method: str,
        route_name: str,
        path: str,
        query_params: dict[str, list[str]] | None = None,
        vary_headers: dict[str, str] | None = None,
        tenant_id: str | None = None,
    ) -> str:
        """
        Build a canonical cache key.
        
        Args:
            method: HTTP method
            route_name: Name of the route
            path: Request path (after route prefix)
            query_params: Query parameters dict (param -> [values])
            vary_headers: Headers to include in cache key (header -> value)
            tenant_id: Tenant ID for isolation
        
        Returns:
            Canonical cache key string
        """
        # Normalize query params: sort keys and values
        normalized_query = ""
        if query_params:
            sorted_params = sorted(
                (k, sorted(v)) for k, v in query_params.items()
            )
            normalized_query = urlencode(
                [(k, val) for k, vals in sorted_params for val in vals],
                doseq=False,
            )

        # Build vary key from headers
        vary_key = ""
        if vary_headers:
            sorted_headers = sorted(vary_headers.items())
            vary_key = "|".join(f"{k}:{v}" for k, v in sorted_headers)

        # Combine components
        components = [
            method.upper(),
            route_name,
            path,
            normalized_query,
            vary_key,
        ]
        if tenant_id:
            components.insert(0, tenant_id)

        raw_key = "::".join(components)

        # Hash for fixed-length key
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()[:32]

        return f"cache:{key_hash}"

    @staticmethod
    def build_lock_key(cache_key: str) -> str:
        """Build a lock key for stampede protection."""
        return f"lock:{cache_key}"

    @staticmethod
    def build_inflight_key(cache_key: str) -> str:
        """Build a key for tracking in-flight requests."""
        return f"inflight:{cache_key}"


@dataclass
class InFlightRequest:
    """Tracks an in-flight request for coalescing."""

    event: asyncio.Event = field(default_factory=asyncio.Event)
    result: CacheEntry | None = None
    error: Exception | None = None


class CacheService:
    """
    High-performance caching service with SWR and stampede protection.
    
    Features:
    - TTL-based caching with configurable expiration
    - Stale-while-revalidate for improved latency
    - Distributed lock-based stampede protection
    - In-process request coalescing for identical requests
    """

    def __init__(self, redis: RedisClient | None = None) -> None:
        self._redis = redis or redis_client
        self._in_flight: dict[str, InFlightRequest] = {}
        self._in_flight_lock = asyncio.Lock()

    async def get(self, cache_key: str) -> CacheResult:
        """
        Get a cached entry.
        
        Returns:
            CacheResult with status and entry (if found)
        """
        try:
            data = await self._redis.get(cache_key)
            if not data:
                return CacheResult(status=CacheEntryStatus.MISS)

            entry = CacheEntry.from_json(data)
            status = entry.get_status()

            # Check if expired beyond stale window
            if status == CacheEntryStatus.MISS:
                await self._redis.delete(cache_key)
                return CacheResult(status=CacheEntryStatus.MISS)

            return CacheResult(
                status=status,
                entry=entry,
                needs_refresh=status == CacheEntryStatus.STALE,
            )

        except Exception as e:
            logger.warning("Cache get error", key=cache_key, error=str(e))
            return CacheResult(status=CacheEntryStatus.MISS)

    async def set(
        self,
        cache_key: str,
        entry: CacheEntry,
    ) -> bool:
        """
        Store an entry in the cache.
        
        Args:
            cache_key: The cache key
            entry: The cache entry to store
        
        Returns:
            True if stored successfully
        """
        try:
            # Set TTL to include stale window so SWR can work
            total_ttl = entry.ttl_seconds + entry.stale_seconds
            await self._redis.set(
                cache_key,
                entry.to_json(),
                ex=total_ttl,
            )
            return True
        except Exception as e:
            logger.warning("Cache set error", key=cache_key, error=str(e))
            return False

    async def delete(self, cache_key: str) -> bool:
        """Delete a cache entry."""
        try:
            result = await self._redis.delete(cache_key)
            return result > 0
        except Exception as e:
            logger.warning("Cache delete error", key=cache_key, error=str(e))
            return False

    async def purge_by_prefix(self, prefix: str) -> int:
        """
        Purge all cache entries matching a prefix.
        
        Note: In production, consider using Redis SCAN for large datasets.
        """
        # This is a simplified implementation
        # In production, use SCAN with pattern matching
        logger.info("Cache purge requested", prefix=prefix)
        return 0  # Would return count of deleted keys

    async def acquire_refresh_lock(
        self,
        cache_key: str,
        timeout: int = 30,
    ) -> bool:
        """
        Acquire a lock for cache refresh (stampede protection).
        
        Only one request should refresh a stale entry at a time.
        
        Args:
            cache_key: The cache key to lock
            timeout: Lock timeout in seconds
        
        Returns:
            True if lock acquired
        """
        lock_key = CacheKeyBuilder.build_lock_key(cache_key)
        return await self._redis.acquire_lock(lock_key, timeout=timeout)

    async def release_refresh_lock(self, cache_key: str) -> bool:
        """Release a refresh lock."""
        lock_key = CacheKeyBuilder.build_lock_key(cache_key)
        return await self._redis.release_lock(lock_key)

    async def wait_for_inflight(
        self,
        cache_key: str,
        timeout: float = 5.0,
    ) -> CacheEntry | None:
        """
        Wait for an in-flight request to complete (request coalescing).
        
        If another request is already fetching this resource, wait for it
        instead of making a duplicate upstream request.
        
        Args:
            cache_key: The cache key to wait for
            timeout: Maximum wait time in seconds
        
        Returns:
            The cached entry if the in-flight request completed, None otherwise
        """
        async with self._in_flight_lock:
            if cache_key not in self._in_flight:
                return None
            request = self._in_flight[cache_key]

        try:
            await asyncio.wait_for(request.event.wait(), timeout=timeout)
            if request.error:
                raise request.error
            return request.result
        except asyncio.TimeoutError:
            return None

    async def register_inflight(self, cache_key: str) -> InFlightRequest | None:
        """
        Register an in-flight request for coalescing.
        
        Returns:
            InFlightRequest if this is the first request, None if another
            request is already in flight (caller should wait instead).
        """
        async with self._in_flight_lock:
            if cache_key in self._in_flight:
                return None

            request = InFlightRequest()
            self._in_flight[cache_key] = request
            return request

    async def complete_inflight(
        self,
        cache_key: str,
        result: CacheEntry | None = None,
        error: Exception | None = None,
    ) -> None:
        """
        Complete an in-flight request, notifying all waiters.
        
        Args:
            cache_key: The cache key
            result: The cache entry result (if successful)
            error: The error (if failed)
        """
        async with self._in_flight_lock:
            request = self._in_flight.pop(cache_key, None)
            if request:
                request.result = result
                request.error = error
                request.event.set()

    async def get_or_fetch(
        self,
        cache_key: str,
        fetch_fn: Any,  # Callable[[], Awaitable[CacheEntry]]
        ttl_seconds: int = 300,
        stale_seconds: int = 60,
    ) -> tuple[CacheEntry, CacheEntryStatus]:
        """
        Get from cache or fetch from upstream with full protection.
        
        This method implements:
        1. Cache lookup
        2. SWR (return stale + async refresh)
        3. Stampede protection (only one fetch per key)
        4. Request coalescing (waiters share result)
        
        Args:
            cache_key: The cache key
            fetch_fn: Async function to fetch fresh data
            ttl_seconds: Cache TTL
            stale_seconds: SWR window
        
        Returns:
            Tuple of (CacheEntry, CacheEntryStatus)
        """
        # Step 1: Check cache
        cache_result = await self.get(cache_key)

        if cache_result.status == CacheEntryStatus.FRESH:
            return cache_result.entry, CacheEntryStatus.FRESH  # type: ignore

        if cache_result.status == CacheEntryStatus.STALE:
            # Trigger background refresh if we get the lock
            if await self.acquire_refresh_lock(cache_key, timeout=10):
                asyncio.create_task(
                    self._background_refresh(cache_key, fetch_fn, ttl_seconds, stale_seconds)
                )
            return cache_result.entry, CacheEntryStatus.STALE  # type: ignore

        # Step 2: Cache miss - try to register as fetcher
        inflight = await self.register_inflight(cache_key)

        if inflight is None:
            # Another request is fetching - wait for it
            result = await self.wait_for_inflight(cache_key)
            if result:
                return result, CacheEntryStatus.MISS
            # Timeout waiting - fetch ourselves
            inflight = await self.register_inflight(cache_key)
            if inflight is None:
                # Still couldn't register - try direct fetch
                entry = await fetch_fn()
                return entry, CacheEntryStatus.MISS

        # Step 3: We're the fetcher - acquire lock and fetch
        try:
            if await self.acquire_refresh_lock(cache_key, timeout=30):
                try:
                    entry = await fetch_fn()
                    await self.set(cache_key, entry)
                    await self.complete_inflight(cache_key, result=entry)
                    return entry, CacheEntryStatus.MISS
                finally:
                    await self.release_refresh_lock(cache_key)
            else:
                # Couldn't get lock - someone else is fetching
                result = await self.wait_for_inflight(cache_key, timeout=5.0)
                if result:
                    return result, CacheEntryStatus.MISS
                # Give up and fetch directly
                entry = await fetch_fn()
                await self.complete_inflight(cache_key, result=entry)
                return entry, CacheEntryStatus.MISS

        except Exception as e:
            await self.complete_inflight(cache_key, error=e)
            raise

    async def _background_refresh(
        self,
        cache_key: str,
        fetch_fn: Any,
        ttl_seconds: int,
        stale_seconds: int,
    ) -> None:
        """Background task to refresh stale cache entries."""
        try:
            entry = await fetch_fn()
            await self.set(cache_key, entry)
            logger.debug("Background cache refresh completed", key=cache_key)
        except Exception as e:
            logger.warning("Background cache refresh failed", key=cache_key, error=str(e))
        finally:
            await self.release_refresh_lock(cache_key)


# Metrics tracking
class CacheMetrics:
    """Simple cache metrics collector."""

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0
        self.stale_hits = 0
        self.errors = 0

    def record_hit(self) -> None:
        self.hits += 1

    def record_miss(self) -> None:
        self.misses += 1

    def record_stale(self) -> None:
        self.stale_hits += 1

    def record_error(self) -> None:
        self.errors += 1

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses + self.stale_hits
        if total == 0:
            return 0.0
        return (self.hits + self.stale_hits) / total

    def to_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "stale_hits": self.stale_hits,
            "errors": self.errors,
            "hit_rate": self.hit_rate,
        }


# Global metrics instance
cache_metrics = CacheMetrics()


# Global cache service instance
cache_service = CacheService()


async def get_cache_service() -> CacheService:
    """Dependency to get cache service."""
    return cache_service
