# Heliox Proxy

## 1. Project Overview
Heliox Proxy is an API gateway that front-ends upstream services with API-key auth,
route-based proxying, response caching, and rate/abuse controls. It is designed for
teams that want a single entry point with predictable limits and observability.

Intentionally out of scope:
- OAuth/OIDC, user sessions, or identity federation (API keys only).
- Service discovery, health-based routing, or multi-region failover.
- Full analytics pipeline or billing.

## 2. Architecture & Data Flow
Components:
- `apps/gateway-api`: FastAPI gateway, auth, routing, caching, logging.
- `apps/worker`: Celery worker (background tasks; minimal use in this repo).
- `ui/admin`: Next.js admin UI for managing routes/policies.
- Postgres: stores tenants, routes, policies, API keys, request logs.
- Redis: cache, rate limit counters, bloom filter for negative caching.

ASCII diagram:
```
Client
  |
  v
FastAPI Gateway (/g/{route}/{path})
  |  Auth + Route Match + Rate/Quota + Abuse
  |  Cache (Redis) + Bloom filter
  v
Upstream Service
  |
  v
Response -> Client
  |
  v
Request Log (Postgres, async background task)
```

Primary execution path:
1. `gateway_proxy_handler` receives `/g/{route}/{path}`.
2. `GatewayRouter` authenticates API key, matches route, checks abuse/rate/quota.
3. `GatewayProxy` builds a cache key and serves from cache if possible.
4. If cache miss or bypass, it proxies upstream and returns the response.
5. Request metadata is logged asynchronously to Postgres.

## 3. Design Principles
1. **Fail closed on auth** → `GatewayRouter.authenticate` blocks missing/invalid keys.
2. **Bounded resource usage** → rate limits, quotas, and cache TTLs are explicit.
3. **Best-effort caching** → cache failures fall back to direct upstream fetches.
4. **Traceable by default** → request IDs and structured logs are emitted on every request.

## 4. Critical Workflows
**Gateway proxy request**
1. Validate API key and tenant status.
2. Match route + policy based on path and method.
3. Apply abuse checks, rate limits, and quotas.
4. Fetch from cache (fresh/stale) or proxy upstream.
5. Persist a request log entry in the background.

State, retries, and recovery:
- Cache entries persist in Redis with TTL + SWR; stale entries are refreshed in the background.
- Rate/abuse counters persist in Redis; in demo mode they fall back to in-memory.
- Request logs are best-effort; failures do not block the response.

## 5. Failure Modes & Guarantees
- **Upstream timeout** → 504 with `upstream_timeout` error type.
- **Upstream error** → 502 with `upstream_error` error type.
- **Redis unavailable** → in-memory fallback (no cross-instance consistency).
- **Database unavailable** → auth/route lookups can fail with 500; request log write may be skipped.

Guarantees:
- Cache is best-effort; responses may be served uncached on cache failure.
- Rate limiting is best-effort when Redis is unavailable.
- Request logging is at-most-once and non-blocking.

## 6. Testing Strategy
Tested:
- Cache key canonicalization and cache entry behavior.
- Cache service coalescing/stale refresh logic.
- Rate limit, abuse scoring, and bloom filter behaviors.

Not tested:
- End-to-end gateway flow with live Postgres/Redis and upstream services.
- UI/admin workflows.

## 7. Tradeoffs & Alternatives
- **Redis vs in-process cache**: Redis provides shared state; demo mode trades consistency for simplicity.
- **API key auth vs OAuth**: API keys keep the gateway small and deterministic.
- **No upstream health checks**: keeps the proxy predictable but shifts resiliency to clients.

## 8. Operational Considerations
- Logging: structured JSON via `structlog`, request IDs propagate to logs.
- Metrics: cache/rate limiter counters exist in-process; no external metrics exporter.
- Debugging: use `X-Request-Id` and request logs in Postgres.
- Risks: Redis instability reduces rate limiting/caching effectiveness.

## 9. Running Locally
Prereqs: Python 3.11, Postgres, Redis.

```
cd apps/gateway-api
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Start dependencies (from repo root):
```
docker compose -f infra/docker-compose.yml up -d
```

Run the gateway:
```
uvicorn src.main:app --reload
```

## 10. Scope & Limitations
- API-key only authentication.
- Single-region, single-instance assumptions in demo mode.
- No automated upstream failover or service discovery.
- Request logs are not guaranteed if the database is unavailable.
