"""API Key model - authentication tokens for tenants."""

import secrets
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.block_rule import BlockRule
    from src.models.request_log import RequestLog
    from src.models.tenant import Tenant


class ApiKeyStatus(str, Enum):
    """Status of an API key."""

    ACTIVE = "active"
    DISABLED = "disabled"
    REVOKED = "revoked"
    EXPIRED = "expired"


def generate_api_key() -> str:
    """Generate a secure API key with prefix."""
    return f"hx_{secrets.token_urlsafe(32)}"


class ApiKey(Base):
    """
    API Key for authenticating requests to the gateway.
    
    Keys are associated with a tenant and have usage quotas.
    """

    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    tenant_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        unique=True,
        index=True,
        default=generate_api_key,
    )
    key_prefix: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
    )
    status: Mapped[ApiKeyStatus] = mapped_column(
        String(20),
        default=ApiKeyStatus.ACTIVE,
    )

    # Quotas (0 = unlimited)
    quota_daily: Mapped[int] = mapped_column(Integer, default=0)
    quota_monthly: Mapped[int] = mapped_column(Integer, default=0)

    # Rate limiting overrides (null = use defaults)
    rate_limit_rps: Mapped[float | None] = mapped_column(nullable=True)
    rate_limit_burst: Mapped[int | None] = mapped_column(nullable=True)

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
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship("Tenant", back_populates="api_keys")
    request_logs: Mapped[list["RequestLog"]] = relationship(
        "RequestLog",
        back_populates="api_key",
        cascade="all, delete-orphan",
    )
    block_rules: Mapped[list["BlockRule"]] = relationship(
        "BlockRule",
        back_populates="api_key",
        cascade="all, delete-orphan",
    )

    def __init__(self, **kwargs: object) -> None:
        """Initialize API key with auto-generated key prefix."""
        super().__init__(**kwargs)
        if self.key and not self.key_prefix:
            self.key_prefix = self.key[:10]

    @property
    def is_active(self) -> bool:
        """Check if the key is active and not expired."""
        if self.status != ApiKeyStatus.ACTIVE:
            return False
        if self.expires_at and self.expires_at < datetime.now(self.expires_at.tzinfo):
            return False
        return True

    def __repr__(self) -> str:
        return f"<ApiKey(id={self.id}, prefix={self.key_prefix}, status={self.status})>"
