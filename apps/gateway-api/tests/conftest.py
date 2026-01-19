"""Pytest configuration and shared fixtures."""

import asyncio
import os
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import sessionmaker

# Set test environment before imports
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["DATABASE_URL_SYNC"] = "sqlite:///:memory:"
os.environ["REDIS_URL"] = ""  # Demo mode
os.environ["SECRET_KEY"] = "test-secret-key-for-testing"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
os.environ["AUTO_SEED"] = "false"
os.environ["DEBUG"] = "true"

from src.config import Settings, get_settings
from src.database import Base, get_db
from src.main import app
from src.models import ApiKey, CachePolicy, Route, Tenant
from src.models.api_key import ApiKeyStatus


@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def settings() -> Settings:
    """Get test settings."""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        database_url_sync="sqlite:///:memory:",
        redis_url="",
        secret_key="test-secret-key-for-testing",
        admin_api_key="test-admin-key",
        auto_seed=False,
        debug=True,
    )


@pytest_asyncio.fixture
async def async_engine():
    """Create async test database engine."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create database session for tests."""
    async_session = async_sessionmaker(
        async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def sample_tenant(db_session: AsyncSession) -> Tenant:
    """Create a sample tenant."""
    tenant = Tenant(
        name="Northwind Trading",
        description="International import/export company",
        is_active=True,
    )
    db_session.add(tenant)
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture
async def sample_cache_policy(db_session: AsyncSession) -> CachePolicy:
    """Create a sample cache policy."""
    policy = CachePolicy(
        name="Standard Cache",
        description="Default caching policy",
        ttl_seconds=300,
        stale_ttl_seconds=600,
        swr_enabled=True,
        vary_headers=["Accept"],
        cache_query_params=True,
        is_active=True,
    )
    db_session.add(policy)
    await db_session.commit()
    await db_session.refresh(policy)
    return policy


@pytest_asyncio.fixture
async def sample_api_key(db_session: AsyncSession, sample_tenant: Tenant) -> ApiKey:
    """Create a sample API key."""
    api_key = ApiKey(
        tenant_id=sample_tenant.id,
        name="Production Key",
        key="hx_prod_northwind_abc123xyz789",
        status=ApiKeyStatus.ACTIVE,
        quota_daily=10000,
        quota_monthly=250000,
        rate_limit_rps=100,
        rate_limit_burst=200,
    )
    db_session.add(api_key)
    await db_session.commit()
    await db_session.refresh(api_key)
    return api_key


@pytest_asyncio.fixture
async def sample_route(
    db_session: AsyncSession,
    sample_tenant: Tenant,
    sample_cache_policy: CachePolicy,
) -> Route:
    """Create a sample route."""
    route = Route(
        tenant_id=sample_tenant.id,
        cache_policy_id=sample_cache_policy.id,
        name="products",
        description="Product catalog endpoint",
        upstream_url="http://localhost:8001",
        path_prefix="/items",
        methods=["GET"],
        is_active=True,
        strip_prefix=False,
        timeout_seconds=30,
    )
    db_session.add(route)
    await db_session.commit()
    await db_session.refresh(route)
    return route


@pytest.fixture
def client() -> TestClient:
    """Create test client."""
    return TestClient(app)


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Create async test client."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client
