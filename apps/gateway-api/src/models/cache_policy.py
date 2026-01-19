"""Cache Policy model - defines caching behavior for routes."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.route import Route


class CachePolicy(Base):
    """
    Cache Policy defines how responses should be cached.
    
    Supports TTL, stale-while-revalidate, vary headers, and cacheable statuses.
    """

    __tablename__ = "cache_policies"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # TTL settings
    ttl_seconds: Mapped[int] = mapped_column(Integer, default=300)  # 5 minutes
    stale_seconds: Mapped[int] = mapped_column(Integer, default=60)  # 1 minute SWR

    # Vary headers for cache key generation (e.g., ["Accept", "Accept-Encoding"])
    vary_headers_json: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        nullable=False,
    )

    # Cacheable HTTP status codes (e.g., [200, 201, 204])
    cacheable_statuses_json: Mapped[list[int]] = mapped_column(
        JSONB,
        default=lambda: [200, 201, 204, 301, 304],
        nullable=False,
    )

    # Maximum body size to cache (bytes)
    max_body_bytes: Mapped[int] = mapped_column(
        Integer,
        default=10 * 1024 * 1024,  # 10MB
    )

    # Cache control settings
    cache_private: Mapped[bool] = mapped_column(default=False)
    cache_no_store: Mapped[bool] = mapped_column(default=False)

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
    routes: Mapped[list["Route"]] = relationship(
        "Route",
        back_populates="policy",
    )

    @property
    def vary_headers(self) -> list[str]:
        """Get vary headers as a list."""
        return self.vary_headers_json or []

    @property
    def cacheable_statuses(self) -> set[int]:
        """Get cacheable statuses as a set."""
        return set(self.cacheable_statuses_json or [200])

    def is_cacheable_status(self, status_code: int) -> bool:
        """Check if a status code is cacheable."""
        return status_code in self.cacheable_statuses

    def __repr__(self) -> str:
        return f"<CachePolicy(id={self.id}, name={self.name}, ttl={self.ttl_seconds}s)>"
