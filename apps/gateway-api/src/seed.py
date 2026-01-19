"""Database seeding with realistic data."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_db_context
from src.models import ApiKey, CachePolicy, Route, Tenant
from src.models.api_key import ApiKeyStatus

logger = logging.getLogger(__name__)

# Realistic seed data
SEED_TENANTS = [
    {
        "name": "Acme Corporation",
        "description": "Enterprise client - E-commerce platform integration",
        "is_active": True,
    },
    {
        "name": "TechFlow Solutions",
        "description": "SaaS provider - Analytics dashboard backend",
        "is_active": True,
    },
    {
        "name": "CloudBridge Inc",
        "description": "Infrastructure services - API aggregation layer",
        "is_active": True,
    },
]

SEED_API_KEYS = [
    # Acme Corporation keys
    {
        "tenant_index": 0,
        "name": "Production API",
        "key": "hx_prod_acme_7k9m2n4p5q8r1s3t6u0v",
        "status": ApiKeyStatus.ACTIVE,
        "quota_daily": 100000,
        "quota_monthly": 2500000,
        "rate_limit_rps": 500,
        "rate_limit_burst": 1000,
    },
    {
        "tenant_index": 0,
        "name": "Staging Environment",
        "key": "hx_stage_acme_3f5g7h9j2k4l6m8n0p",
        "status": ApiKeyStatus.ACTIVE,
        "quota_daily": 10000,
        "quota_monthly": 250000,
        "rate_limit_rps": 100,
        "rate_limit_burst": 200,
    },
    # TechFlow Solutions keys
    {
        "tenant_index": 1,
        "name": "Analytics Service",
        "key": "hx_prod_techflow_9a1b3c5d7e2f4g6h8i",
        "status": ApiKeyStatus.ACTIVE,
        "quota_daily": 50000,
        "quota_monthly": 1500000,
        "rate_limit_rps": 250,
        "rate_limit_burst": 500,
    },
    {
        "tenant_index": 1,
        "name": "Development Key",
        "key": "hx_dev_techflow_2x4y6z8a0b1c3d5e7f",
        "status": ApiKeyStatus.ACTIVE,
        "quota_daily": 5000,
        "quota_monthly": 100000,
        "rate_limit_rps": 50,
        "rate_limit_burst": 100,
    },
    # CloudBridge Inc keys
    {
        "tenant_index": 2,
        "name": "Gateway Service",
        "key": "hx_prod_cloudbridge_5m7n9p1q3r5s7t9u2v",
        "status": ApiKeyStatus.ACTIVE,
        "quota_daily": 200000,
        "quota_monthly": 5000000,
        "rate_limit_rps": 1000,
        "rate_limit_burst": 2000,
    },
]

SEED_CACHE_POLICIES = [
    {
        "name": "Standard API Cache",
        "description": "Default caching for most API endpoints",
        "ttl_seconds": 300,  # 5 minutes
        "stale_seconds": 60,  # 1 minute SWR window
        "vary_headers_json": ["Accept", "Accept-Language"],
    },
    {
        "name": "High-Frequency Data",
        "description": "Short cache for frequently changing data",
        "ttl_seconds": 30,
        "stale_seconds": 30,
        "vary_headers_json": ["Accept"],
    },
    {
        "name": "Static Content",
        "description": "Long cache for rarely changing content",
        "ttl_seconds": 3600,  # 1 hour
        "stale_seconds": 600,  # 10 minutes SWR
        "vary_headers_json": [],
    },
    {
        "name": "No Cache",
        "description": "Bypass cache for real-time data",
        "ttl_seconds": 0,
        "stale_seconds": 0,
        "vary_headers_json": [],
        "cache_no_store": True,
    },
]

SEED_ROUTES = [
    # Routes pointing to the example upstream service
    {
        "tenant_index": 0,  # Acme Corporation
        "policy_index": 0,  # Standard API Cache
        "name": "products",
        "description": "Product catalog API",
        "upstream_base_url": "http://upstream:8001",
        "path_pattern": "/items/*",
        "methods": ["GET"],
        "is_active": True,
        "timeout_ms": 30000,
    },
    {
        "tenant_index": 0,
        "policy_index": 1,  # High-Frequency Data
        "name": "inventory",
        "description": "Real-time inventory status",
        "upstream_base_url": "http://upstream:8001",
        "path_pattern": "/inventory/*",
        "methods": ["GET"],
        "is_active": True,
        "timeout_ms": 10000,
    },
    {
        "tenant_index": 1,  # TechFlow Solutions
        "policy_index": 0,
        "name": "analytics",
        "description": "Analytics data endpoints",
        "upstream_base_url": "http://upstream:8001",
        "path_pattern": "/stats/*",
        "methods": ["GET"],
        "is_active": True,
        "timeout_ms": 30000,
    },
    {
        "tenant_index": 1,
        "policy_index": 2,  # Static Content
        "name": "reports",
        "description": "Generated reports API",
        "upstream_base_url": "http://upstream:8001",
        "path_pattern": "/large/*",
        "methods": ["GET"],
        "is_active": True,
        "timeout_ms": 60000,
    },
    {
        "tenant_index": 2,  # CloudBridge Inc
        "policy_index": 0,
        "name": "services",
        "description": "Upstream service aggregation",
        "upstream_base_url": "http://upstream:8001",
        "path_pattern": "/*",
        "methods": ["GET", "POST"],
        "is_active": True,
        "timeout_ms": 30000,
    },
    {
        "tenant_index": 2,
        "policy_index": 3,  # No Cache
        "name": "webhooks",
        "description": "Real-time webhook forwarding",
        "upstream_base_url": "http://upstream:8001",
        "path_pattern": "/headers/*",
        "methods": ["GET", "POST"],
        "is_active": True,
        "timeout_ms": 5000,
    },
    # Demo route for quick testing (shared route - no tenant)
    {
        "tenant_index": None,
        "policy_index": 0,
        "name": "demo",
        "description": "Demo endpoint for testing gateway features",
        "upstream_base_url": "http://upstream:8001",
        "path_pattern": "/*",
        "methods": ["GET", "POST"],
        "is_active": True,
        "timeout_ms": 30000,
        "priority": 10,  # Lower priority, matched last
    },
]


async def seed_database(db: AsyncSession) -> dict:
    """Seed database with realistic data. Returns summary of created entities."""
    
    summary = {
        "tenants_created": 0,
        "api_keys_created": 0,
        "cache_policies_created": 0,
        "routes_created": 0,
        "skipped": False,
    }
    
    # Check if already seeded
    existing = await db.execute(select(Tenant).limit(1))
    if existing.scalar_one_or_none():
        logger.info("Database already seeded, skipping")
        summary["skipped"] = True
        return summary
    
    logger.info("Seeding database with initial data...")
    
    # Create tenants
    tenants = []
    for tenant_data in SEED_TENANTS:
        tenant = Tenant(**tenant_data)
        db.add(tenant)
        tenants.append(tenant)
        summary["tenants_created"] += 1
    
    await db.flush()  # Get tenant IDs
    
    # Create cache policies
    policies = []
    for policy_data in SEED_CACHE_POLICIES:
        policy = CachePolicy(**policy_data)
        db.add(policy)
        policies.append(policy)
        summary["cache_policies_created"] += 1
    
    await db.flush()  # Get policy IDs
    
    # Create API keys
    for key_data in SEED_API_KEYS:
        tenant_index = key_data.pop("tenant_index")
        key = ApiKey(
            tenant_id=tenants[tenant_index].id,
            **key_data
        )
        db.add(key)
        summary["api_keys_created"] += 1
    
    # Create routes
    for route_data in SEED_ROUTES:
        route_data = route_data.copy()  # Don't mutate original
        tenant_index = route_data.pop("tenant_index")
        policy_index = route_data.pop("policy_index")
        route = Route(
            tenant_id=tenants[tenant_index].id if tenant_index is not None else None,
            policy_id=policies[policy_index].id,
            **route_data
        )
        db.add(route)
        summary["routes_created"] += 1
    
    await db.commit()
    
    logger.info(
        f"Database seeded: {summary['tenants_created']} tenants, "
        f"{summary['api_keys_created']} API keys, "
        f"{summary['cache_policies_created']} cache policies, "
        f"{summary['routes_created']} routes"
    )
    
    return summary


async def run_seed():
    """Run seeding as standalone script."""
    async with get_db_context() as db:
        return await seed_database(db)


if __name__ == "__main__":
    asyncio.run(run_seed())
