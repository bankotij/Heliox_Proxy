# Heliox Proxy

Heliox Proxy is an **API gateway** that fronts upstream services with **API-key authentication**, **route-based proxying**, **response caching**, and **rate / quota / abuse** controls—plus structured **request logging** to Postgres and a **Next.js admin UI** for routes, keys, and observability.

**Intentionally out of scope:** OAuth/OIDC, service discovery, multi-region failover, full billing/analytics pipelines.

---

## Screenshot (admin UI)

![Heliox admin console](docs/screenshots/admin-dashboard.png)

> **Note:** Add your own capture at `docs/screenshots/admin-dashboard.png` (or update this path). Until then the image may not render on GitHub.

---

## Architecture

```
                    ┌─────────────────────┐
                    │   Next.js Admin UI   │
                    │   (routes, logs)     │
                    └──────────┬───────────┘
                               │
 Client ──► FastAPI Gateway ────┼──► Postgres (tenants, routes, policies, keys, logs)
    │           │               │
    │           ├──► Redis (cache, rate limits, bloom / negative cache)
    │           │
    └── X-Request-Id / structured logs
                               │
                               ▼
                         Upstream APIs
```

**Components**

| Path | Role |
|------|------|
| `apps/gateway-api` | FastAPI: `/g/{route}/{path}`, auth, cache, limits, logging |
| `apps/worker` | Celery worker (minimal in this repo) |
| `ui/admin` | Next.js admin for configuration and log inspection |
| Postgres | Tenants, routes, policies, API keys, request logs |
| Redis | Cache entries, rate-limit counters, bloom filter |

**Primary request path**

1. `gateway_proxy_handler` receives `/g/{route}/{path}`.
2. `GatewayRouter` authenticates the API key, matches route + policy.
3. Abuse checks, rate limits, quotas.
4. `GatewayProxy` builds cache key → Redis hit (fresh/stale) or upstream fetch.
5. Response returned; request metadata logged **asynchronously** to Postgres.

---

## 60-second demo

1. From repo root, start dependencies: `docker compose -f infra/docker-compose.yml up -d` (Postgres, Redis, etc.).
2. Run the gateway API (see **Running locally** below) and the admin UI (`cd ui/admin && npm run dev`) if you want the console.
3. Use a **seeded or created API key** and call the gateway: `GET` or `POST` through `/g/{route}/{path}` as configured for your tenant.
4. Repeat the same request and observe **cache behavior** (fresh vs stale / bypass) via response headers or logs.
5. Open the **admin UI** and confirm **request logs** for your calls.
6. Run **pytest** (below) to show gateway behavior is covered by automated tests.

---

## Running locally

**Prerequisites:** Python 3.11+, Postgres, Redis.

```bash
cd apps/gateway-api
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Start dependencies from repo root:

```bash
docker compose -f infra/docker-compose.yml up -d
```

Run the gateway:

```bash
cd apps/gateway-api
uvicorn src.main:app --reload
```

Admin UI (optional):

```bash
cd ui/admin
npm install && npm run dev
# opens http://localhost:3000 by default
```

---

## Tests

From `apps/gateway-api` with dependencies running:

```bash
cd apps/gateway-api
pytest -q
```

Targeted examples:

```bash
pytest -q tests/test_cache.py tests/test_gateway_proxy.py
```

**What is covered:** cache keys, cache service behavior, rate limiting, abuse scoring, bloom filter, gateway proxy paths (see `tests/`).

**What is not fully covered:** live end-to-end runs against real Postgres + Redis + upstream in CI; **admin UI** flows are manual.

---

## Design principles

1. **Fail closed on auth** — invalid or missing API keys are rejected.
2. **Bounded usage** — explicit rate limits, quotas, cache TTLs.
3. **Best-effort caching** — if Redis misbehaves, responses may bypass cache.
4. **Traceable** — request IDs and structured logs on every request.

## Failure modes & guarantees

| Situation | Behavior |
|-----------|----------|
| Upstream timeout | **504** (`upstream_timeout`) |
| Upstream error | **502** (`upstream_error`) |
| Redis down | In-memory **fallback** for some paths — **no cross-instance consistency** |
| Database down | Route/key lookup may **500**; request log write may be skipped |

Request logging is **best-effort** and must not block the client response.

---

## Production gaps (honest)

- **Single-region / demo assumptions** unless you add HA Postgres/Redis and gateway replicas.
- **No OAuth** — API keys only; human SSO is out of scope here.
- **No upstream health-aware routing** — clients handle retries.
- **Metrics** are largely in-process; no Prometheus exporter in-tree.
- **Admin UI** E2E not automated.
- **Redis fallback** improves local/dev UX but is **not** a multi-node ratelimit story.

---

## Operational notes

- Logging: **structlog** JSON; propagate **`X-Request-Id`**.
- Debugging: correlate gateway logs with rows in Postgres request logs.
- Risk: Redis instability weakens cache + distributed rate limiting.

---

## Scope recap

- API-key authentication only.
- Deliberately small surface: proxy + guardrails + observability, not a full API management suite.
