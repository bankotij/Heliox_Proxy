"""Application configuration with environment variable support."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://heliox:heliox_password@localhost:5432/heliox",
        description="Async PostgreSQL connection URL",
    )
    database_url_sync: str = Field(
        default="postgresql://heliox:heliox_password@localhost:5432/heliox",
        description="Sync PostgreSQL connection URL (for Alembic)",
    )

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL. Empty string enables demo mode.",
    )

    # Application
    secret_key: str = Field(
        default="dev-secret-key-change-in-production",
        min_length=16,
    )
    admin_api_key: str = Field(
        default="admin-secret-key",
        description="API key for admin endpoints",
    )
    debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    # Gateway settings
    default_upstream_timeout_ms: int = Field(default=30000)
    max_cache_body_size: int = Field(default=10 * 1024 * 1024)  # 10MB

    # Rate limiting
    default_rate_limit_rps: float = Field(default=100.0)
    default_rate_limit_burst: int = Field(default=200)

    # Abuse detection
    abuse_ewma_alpha: float = Field(default=0.3, ge=0.0, le=1.0)
    abuse_zscore_threshold: float = Field(default=3.0)
    abuse_block_duration_seconds: int = Field(default=300)

    # Bloom filter
    bloom_expected_items: int = Field(default=10000)
    bloom_false_positive_rate: float = Field(default=0.01)

    # Celery
    celery_broker_url: str = Field(default="redis://localhost:6379/1")
    celery_result_backend: str = Field(default="redis://localhost:6379/1")

    # CORS
    cors_origins: str = Field(default="http://localhost:3000")

    # Deployment mode
    deployment_mode: Literal["full", "demo"] = Field(default="full")
    
    # Auto-seed database on startup
    auto_seed: bool = Field(
        default=True,
        description="Automatically seed database with initial data on startup",
    )

    @field_validator("cors_origins")
    @classmethod
    def parse_cors_origins(cls, v: str) -> str:
        """Keep as string, will be split when needed."""
        return v

    @property
    def cors_origins_list(self) -> list[str]:
        """Return CORS origins as a list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_demo_mode(self) -> bool:
        """Check if running in demo mode (no Redis)."""
        return self.deployment_mode == "demo" or not self.redis_url

    @property
    def redis_available(self) -> bool:
        """Check if Redis is configured."""
        return bool(self.redis_url)


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
