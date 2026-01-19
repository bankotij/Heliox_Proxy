"""Block Rule model - stores temporary blocks from abuse detection."""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.database import Base

if TYPE_CHECKING:
    from src.models.api_key import ApiKey


class BlockReason(str, Enum):
    """Reasons for blocking an API key."""

    RATE_SPIKE = "rate_spike"
    ERROR_RATE_SPIKE = "error_rate_spike"
    QUOTA_ABUSE = "quota_abuse"
    MANUAL = "manual"
    SUSPICIOUS_PATTERN = "suspicious_pattern"


class BlockRule(Base):
    """
    Block Rule represents a temporary or permanent block on an API key.
    
    Created by abuse detection or manual admin action.
    """

    __tablename__ = "block_rules"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    # Association
    api_key_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("api_keys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Block details
    reason: Mapped[BlockReason] = mapped_column(String(30), nullable=False)
    reason_detail: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Scoring data at time of block
    anomaly_score: Mapped[float | None] = mapped_column(nullable=True)
    rate_at_block: Mapped[float | None] = mapped_column(nullable=True)
    error_rate_at_block: Mapped[float | None] = mapped_column(nullable=True)

    # Block timing
    blocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    blocked_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,  # null = permanent until manual unblock
    )

    # Resolution
    unblocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    unblocked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unblock_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Relationships
    api_key: Mapped["ApiKey"] = relationship("ApiKey", back_populates="block_rules")

    @property
    def is_active(self) -> bool:
        """Check if this block is currently active."""
        now = datetime.now(tz=self.blocked_at.tzinfo if self.blocked_at else None)

        # Already unblocked
        if self.unblocked_at is not None:
            return False

        # Temporary block expired
        if self.blocked_until is not None and self.blocked_until < now:
            return False

        return True

    @property
    def is_permanent(self) -> bool:
        """Check if this is a permanent block."""
        return self.blocked_until is None

    def __repr__(self) -> str:
        status = "active" if self.is_active else "inactive"
        return f"<BlockRule(id={self.id}, reason={self.reason}, status={status})>"
