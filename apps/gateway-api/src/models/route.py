"""Route model - defines gateway routing rules."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.cache_policy import CachePolicy
    from src.models.request_log import RequestLog
    from src.models.tenant import Tenant


class Route(Base):
    """
    Route defines how to proxy requests to upstream services.
    
    Routes can be tenant-specific or shared (tenant_id = null).
    """

    __tablename__ = "routes"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Tenant association (null = shared route available to all)
    tenant_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Routing configuration
    path_pattern: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        index=True,
    )
    methods: Mapped[list[str]] = mapped_column(
        JSONB,
        default=lambda: ["GET", "POST", "PUT", "PATCH", "DELETE"],
        nullable=False,
    )

    # Upstream configuration
    upstream_base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    upstream_path_rewrite: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    timeout_ms: Mapped[int] = mapped_column(Integer, default=30000)

    # Request/Response transformations (headers to add/remove)
    request_headers_add: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    request_headers_remove: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )
    response_headers_add: Mapped[dict[str, str]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    # Cache policy
    policy_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("cache_policies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Rate limiting overrides for this route
    rate_limit_rps: Mapped[float | None] = mapped_column(nullable=True)
    rate_limit_burst: Mapped[int | None] = mapped_column(nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(default=True)
    priority: Mapped[int] = mapped_column(Integer, default=0)  # Higher = matched first

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    tenant: Mapped["Tenant | None"] = relationship("Tenant", back_populates="routes")
    policy: Mapped["CachePolicy | None"] = relationship("CachePolicy", back_populates="routes")
    request_logs: Mapped[list["RequestLog"]] = relationship(
        "RequestLog",
        back_populates="route",
        cascade="all, delete-orphan",
    )

    def matches_method(self, method: str) -> bool:
        """Check if this route handles the given HTTP method."""
        return method.upper() in [m.upper() for m in (self.methods or [])]

    def get_upstream_url(self, path: str) -> str:
        """Build the full upstream URL for a given path."""
        base = self.upstream_base_url.rstrip("/")
        if self.upstream_path_rewrite:
            # Simple rewrite: replace the route name portion
            path = self.upstream_path_rewrite + path
        return f"{base}{path}"

    def __repr__(self) -> str:
        return f"<Route(id={self.id}, name={self.name}, pattern={self.path_pattern})>"
