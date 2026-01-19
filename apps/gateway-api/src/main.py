"""Main FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from src import __version__
from src.api.admin import router as admin_router
from src.api.algorithms import router as algorithms_router
from src.api.gateway import router as gateway_router
from src.api.health import router as health_router
from src.config import get_settings
from src.database import close_db, get_db_context, init_db
from src.gateway.proxy import gateway_proxy
from src.middleware.logging import LoggingMiddleware, setup_logging
from src.middleware.request_id import RequestIdMiddleware
from src.services.redis_client import redis_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """Application lifespan handler."""
    settings = get_settings()
    
    # Startup
    setup_logging()
    
    # Connect to Redis
    await redis_client.connect()
    
    # Initialize database (create tables if needed)
    await init_db()
    
    # Auto-seed database if enabled
    if settings.auto_seed:
        from src.seed import seed_database
        async with get_db_context() as db:
            result = await seed_database(db)
            if not result.get("skipped"):
                logger.info(f"Auto-seeded database: {result}")
    
    yield
    
    # Shutdown
    await gateway_proxy.close()
    await redis_client.disconnect()
    await close_db()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()
    
    app = FastAPI(
        title="Heliox Gateway",
        description="Production-grade API Gateway with caching, rate limiting, and abuse detection",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
    )
    
    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Add custom middleware (order matters - first added is outermost)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(RequestIdMiddleware)
    
    # Include routers
    app.include_router(health_router)
    app.include_router(gateway_router)
    app.include_router(admin_router)
    app.include_router(algorithms_router)
    
    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
