"""
Example upstream service for demonstrating Heliox Gateway features.

This service provides endpoints that simulate various upstream behaviors:
- Slow responses (for caching demos)
- Flaky responses (for error handling demos)
- Items with some 404s (for bloom filter demos)
"""

import asyncio
import random
import time
from datetime import datetime

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import JSONResponse

app = FastAPI(
    title="Example Upstream Service",
    description="Demo service for testing Heliox Gateway",
    version="1.0.0",
)

# Simulated database of items
ITEMS = {
    "1": {"id": "1", "name": "Widget A", "price": 9.99, "in_stock": True},
    "2": {"id": "2", "name": "Widget B", "price": 19.99, "in_stock": True},
    "3": {"id": "3", "name": "Gadget X", "price": 49.99, "in_stock": False},
    "5": {"id": "5", "name": "Gadget Y", "price": 79.99, "in_stock": True},
    "10": {"id": "10", "name": "Premium Item", "price": 199.99, "in_stock": True},
}

# Track request count for demos
request_counter = {"total": 0, "by_endpoint": {}}


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "Example Upstream",
        "version": "1.0.0",
        "endpoints": [
            "/slow - Simulates slow response",
            "/flaky - Random failures",
            "/items/{id} - Item lookup (some 404s)",
            "/items - List all items",
            "/stats - Request statistics",
        ],
    }


@app.get("/slow")
async def slow_endpoint(
    delay: float = Query(2.0, ge=0.1, le=10.0, description="Delay in seconds"),
):
    """
    Endpoint that simulates a slow upstream response.
    
    Use this to demonstrate:
    - Cache benefits (cached responses are instant)
    - SWR (stale responses served while refreshing)
    """
    _count_request("/slow")
    
    await asyncio.sleep(delay)
    
    return {
        "message": "This was a slow response",
        "delay_seconds": delay,
        "timestamp": datetime.utcnow().isoformat(),
        "tip": "With caching, subsequent requests will be instant!",
    }


@app.get("/flaky")
async def flaky_endpoint(
    failure_rate: float = Query(0.3, ge=0.0, le=1.0, description="Probability of failure"),
):
    """
    Endpoint that randomly fails.
    
    Use this to demonstrate:
    - Error handling
    - Abuse detection (high error rates)
    - Circuit breaker patterns
    """
    _count_request("/flaky")
    
    if random.random() < failure_rate:
        status_code = random.choice([500, 502, 503, 504])
        raise HTTPException(
            status_code=status_code,
            detail=f"Random failure with status {status_code}",
        )
    
    return {
        "message": "Success! (this time)",
        "failure_rate": failure_rate,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/items")
async def list_items(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
):
    """
    List all available items.
    
    Demonstrates basic caching of list endpoints.
    """
    _count_request("/items")
    
    items = list(ITEMS.values())
    start = (page - 1) * page_size
    end = start + page_size
    
    return {
        "items": items[start:end],
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/items/{item_id}")
async def get_item(item_id: str):
    """
    Get a specific item by ID.
    
    Use this to demonstrate:
    - Bloom filter for 404s (items 4, 6, 7, 8, 9 don't exist)
    - Per-resource caching
    
    Existing items: 1, 2, 3, 5, 10
    Missing items: 4, 6, 7, 8, 9, 11+
    """
    _count_request(f"/items/{item_id}")
    
    if item_id in ITEMS:
        return {
            **ITEMS[item_id],
            "timestamp": datetime.utcnow().isoformat(),
        }
    
    raise HTTPException(
        status_code=404,
        detail=f"Item {item_id} not found",
    )


@app.post("/items")
async def create_item(item: dict):
    """
    Create a new item (simulated).
    
    POST requests typically bypass cache.
    """
    _count_request("/items POST")
    
    new_id = str(max(int(k) for k in ITEMS.keys()) + 1)
    
    return {
        "id": new_id,
        "message": "Item created (simulated)",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/headers")
async def echo_headers(response: Response):
    """
    Echo back request headers.
    
    Useful for debugging header transformations.
    """
    _count_request("/headers")
    
    from starlette.requests import Request
    # This is a simplified version - in real code we'd inject the request
    return {
        "message": "Check X-Forwarded-* headers",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/vary")
async def vary_endpoint(
    response: Response,
    variant: str = Query("default", description="Vary by this parameter"),
):
    """
    Endpoint that varies response by query param.
    
    Demonstrates Vary header caching.
    """
    _count_request("/vary")
    
    response.headers["Vary"] = "Accept, Accept-Encoding"
    
    return {
        "variant": variant,
        "message": f"Response varies by: {variant}",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/large")
async def large_response(
    size_kb: int = Query(100, ge=1, le=10000, description="Response size in KB"),
):
    """
    Generate a large response.
    
    Demonstrates max_body_bytes cache policy setting.
    """
    _count_request("/large")
    
    # Generate approximately size_kb of data
    data = "x" * (size_kb * 1024)
    
    return {
        "size_kb": size_kb,
        "data": data,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/stats")
async def get_stats():
    """
    Get request statistics for this upstream.
    
    Shows how many requests reached the upstream (vs. cached).
    """
    return {
        "total_requests": request_counter["total"],
        "by_endpoint": request_counter["by_endpoint"],
        "message": "Compare these numbers with gateway metrics to see cache effectiveness",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/stats/reset")
async def reset_stats():
    """Reset request statistics."""
    request_counter["total"] = 0
    request_counter["by_endpoint"] = {}
    return {"message": "Stats reset"}


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


def _count_request(endpoint: str) -> None:
    """Track request counts."""
    request_counter["total"] += 1
    request_counter["by_endpoint"][endpoint] = (
        request_counter["by_endpoint"].get(endpoint, 0) + 1
    )


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(app, host="0.0.0.0", port=8001)
