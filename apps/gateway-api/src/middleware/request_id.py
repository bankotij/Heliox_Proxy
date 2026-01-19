"""Request ID middleware for request tracing."""

import uuid
from collections.abc import Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Context variable for request ID
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """Get the current request ID from context."""
    return request_id_ctx.get()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """
    Middleware that adds a unique request ID to each request.
    
    The request ID is:
    - Taken from X-Request-Id header if provided
    - Generated as a UUID if not provided
    - Added to the response as X-Request-Id header
    - Made available via context variable for logging
    """

    HEADER_NAME = "X-Request-Id"

    async def dispatch(
        self,
        request: Request,
        call_next: Callable,
    ) -> Response:
        """Process the request and add request ID."""
        # Get or generate request ID
        request_id = request.headers.get(self.HEADER_NAME)
        if not request_id:
            request_id = str(uuid.uuid4())

        # Store in context for logging
        token = request_id_ctx.set(request_id)

        # Store in request state for handlers
        request.state.request_id = request_id

        try:
            response = await call_next(request)
            # Add request ID to response
            response.headers[self.HEADER_NAME] = request_id
            return response
        finally:
            request_id_ctx.reset(token)
