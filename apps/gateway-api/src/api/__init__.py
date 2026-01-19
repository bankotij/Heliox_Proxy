"""API route handlers."""

from src.api.admin import router as admin_router
from src.api.gateway import router as gateway_router
from src.api.health import router as health_router

__all__ = ["admin_router", "gateway_router", "health_router"]
