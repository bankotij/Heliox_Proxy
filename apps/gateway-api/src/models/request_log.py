"""Request Log model - stores request metrics and audit trail."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.api_key import ApiKey
    from src.models.route import Route
    from src.models.tenant import Tenant


class CacheStatus(str, Enum):
    """Cache hit/miss status."""

    HIT = "hit"
    MISS = "miss"
    STALE = "stale"
    BYPASS = "bypass"


class ErrorType(str, Enum):
    """Error classification for failed requests."""

    NONE = "none"
    AUTH_FAILED = "auth_failed"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXCEEDED = "quota_exceeded"
    BLOCKED = "blocked"
    UPSTREAM_ERROR = "upstream_error"
    UPSTREAM_TIMEOUT = "upstream_timeout"
    VALIDATION_ERROR = "validation_error"
    INTERNAL_ERROR = "internal_error"


class RequestLog(Base):
    """
    Request Log stores metrics for each gateway request.
    
    Used for analytics, debugging, and abuse detection.
    """

    __tablename__ = "request_logs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    # Request identification
    request_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )

    # Associations
    tenant_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("tenants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    api_key_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("api_keys.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    route_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("routes.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Request details
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(2000), nullable=False)
    query_string: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    client_ip: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Response metrics
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    response_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Cache status
    cache_status: Mapped[CacheStatus] = mapped_column(
        String(20),
        default=CacheStatus.MISS,
    )

    # Error tracking
    error_type: Mapped[ErrorType] = mapped_column(
        String(30),
        default=ErrorType.NONE,
    )
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Upstream metrics (if applicable)
    upstream_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upstream_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    tenant: Mapped["Tenant | None"] = relationship("Tenant")
    api_key: Mapped["ApiKey | None"] = relationship("ApiKey", back_populates="request_logs")
    route: Mapped["Route | None"] = relationship("Route", back_populates="request_logs")

    @property
    def is_cache_hit(self) -> bool:
        """Check if this was a cache hit (including stale)."""
        return self.cache_status in (CacheStatus.HIT, CacheStatus.STALE)

    @property
    def is_error(self) -> bool:
        """Check if this request resulted in an error."""
        return self.error_type != ErrorType.NONE

    def __repr__(self) -> str:
        return (
            f"<RequestLog(id={self.id}, path={self.path}, "
            f"status={self.status_code}, cache={self.cache_status})>"
        )
