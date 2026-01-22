"""Tests for gateway proxy behavior."""

import httpx
import pytest
from starlette.requests import Request

from src.gateway.proxy import GatewayProxy
from src.gateway.router import AuthResult, GatewayContext, RouteMatch
from src.models import CachePolicy, Route
from src.models.request_log import CacheStatus, ErrorType


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/g/test/resource",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 1234),
    }
    return Request(scope)


@pytest.mark.asyncio
async def test_proxy_bypasses_cache_for_non_cacheable_status():
    request_count = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(500, json={"error": "upstream"})

    proxy = GatewayProxy(timeout_ms=1000)
    proxy._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    policy = CachePolicy(
        name="cache-200-only",
        cacheable_statuses_json=[200],
        ttl_seconds=60,
        stale_seconds=10,
        max_body_bytes=1024,
    )
    route = Route(
        name="test",
        path_pattern="/{path:path}",
        methods=["GET"],
        upstream_base_url="http://upstream.test",
        timeout_ms=1000,
        request_headers_add={},
        request_headers_remove=[],
        response_headers_add={},
        policy=policy,
    )

    context = GatewayContext(
        auth=AuthResult(authenticated=True),
        route_match=RouteMatch(matched=True, route=route, policy=policy),
    )

    result = await proxy.proxy_request(
        request=_make_request(),
        context=context,
        path="/resource",
    )

    await proxy.close()

    assert result.response.status_code == 500
    assert result.cache_status == CacheStatus.BYPASS
    assert result.error_type == ErrorType.NONE
    assert request_count == 1
