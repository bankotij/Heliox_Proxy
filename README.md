# Heliox Proxy

A **production-grade API Gateway + Caching Proxy** built with Python, FastAPI, Redis, and PostgreSQL. Features real-time admin UI, Redis caching with SWR, stampede protection, request deduplication, and abuse controls.

![Architecture](https://img.shields.io/badge/Architecture-Microservices-blue)
![Python](https://img.shields.io/badge/Python-3.11+-green)
![License](https://img.shields.io/badge/License-MIT-yellow)

## Features

### Core Gateway
- **Configurable Routing**: Path patterns map to upstream services
- **Per-tenant API Keys**: Quotas and rate limits per route
- **Response Caching**: TTL + Stale-While-Revalidate (SWR)
- **Stampede Protection**: Redis locks prevent cache stampedes
- **Request Coalescing**: Deduplicate in-flight requests

### Advanced Features
- **Bloom Filter**: Negative caching for 404-heavy paths
- **Abuse Detection**: EWMA/Z-score anomaly detection with soft blocks
- **Rate Limiting**: Token bucket and sliding window algorithms
- **Quota Management**: Daily and monthly usage quotas

### Admin UI
- Dashboard with real-time metrics
- Tenant and API key management
- Route and cache policy configuration
- Live request logs
- Abuse monitoring and unblock actions

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Client Request                              │
└─────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                           Heliox Gateway                                 │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌──────────────┐  │
│  │ Auth Layer  │──│ Rate Limiter │──│ Cache Check │──│ Abuse Check  │  │
│  └─────────────┘  └──────────────┘  └─────────────┘  └──────────────┘  │
│         │                 │                │                 │          │
│         ▼                 ▼                ▼                 ▼          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                       Request Router                             │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
         │                                          │
         ▼                                          ▼
┌─────────────────┐                      ┌─────────────────┐
│      Redis      │                      │   PostgreSQL    │
│  - Cache Store  │                      │  - Config Data  │
│  - Rate Limits  │                      │  - Request Logs │
│  - Bloom Filter │                      │  - Tenants/Keys │
│  - Locks        │                      └─────────────────┘
└─────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Upstream Services                               │
└─────────────────────────────────────────────────────────────────────────┘
```

### Request Flow

1. **Authentication**: Validate API key from `X-API-Key` header
2. **Rate Limiting**: Check token bucket / sliding window limits
3. **Quota Check**: Verify daily/monthly quotas
4. **Abuse Check**: Verify key isn't blocked by anomaly detection
5. **Route Match**: Find matching route configuration
6. **Cache Lookup**:
   - **HIT**: Return cached response immediately
   - **STALE**: Return stale + enqueue background refresh (SWR)
   - **MISS**: Fetch from upstream with coalescing
7. **Response**: Return to client with cache headers

---

## Caching + SWR Explanation

### Stale-While-Revalidate (SWR)

SWR improves latency by serving stale cached data while refreshing in the background:

```
Time ────────────────────────────────────────────────────────────────────►

│◄─────── TTL (Fresh) ───────►│◄─── Stale Window ───►│◄─── Expired ───►

     Request 1: Cache MISS     Request 2: Cache HIT
     (fetches from upstream)   (instant response)

                                    Request 3: STALE
                                    (instant stale response)
                                    (background refresh starts)

                                                           Request 4: HIT
                                                           (fresh from refresh)
```

**Benefits**:
- Users get instant responses even after TTL expires
- Background refresh happens transparently
- Reduces perceived latency significantly

### Cache Key Canonicalization

Cache keys are built from:
- HTTP Method
- Route name
- Path
- Normalized query parameters (sorted)
- Vary headers (e.g., Accept, Accept-Encoding)
- Tenant ID (for isolation)

```python
# Same key regardless of query param order:
/api/items?color=red&size=large  →  cache:a1b2c3...
/api/items?size=large&color=red  →  cache:a1b2c3...
```

---

## Stampede Protection + Coalescing

### Cache Stampede Problem

Without protection, when a cache entry expires:
- 100 concurrent requests all see cache miss
- All 100 make upstream requests simultaneously
- Upstream gets hammered

### Solution: Distributed Locks + Coalescing

```
Request 1 ──► [Acquires Lock] ──► Fetches Upstream ──► Sets Cache ──► Response
Request 2 ──► [Lock Busy]     ──► Waits ─────────────────────────────► Gets Result
Request 3 ──► [Lock Busy]     ──► Waits ─────────────────────────────► Gets Result
Request 4 ──► [Lock Busy]     ──► Waits ─────────────────────────────► Gets Result
```

**Result**: Only 1 upstream request instead of N.

---

## Bloom Filter for Negative Caching

### Problem

APIs with many 404s waste resources:
- `/items/12345` → 404 (cached)
- `/items/99999` → 404 (not cached, hits upstream)
- Repeated 404 requests hammer upstream

### Solution: Bloom Filter

A probabilistic data structure that answers "probably yes" or "definitely no":

```
┌───────────────────────────────────────┐
│           Bloom Filter                │
│  ┌─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┬─┐   │
│  │0│0│1│0│1│0│0│1│0│1│0│0│1│0│0│1│   │  ← Bit array
│  └─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┴─┘   │
│          ▲           ▲       ▲        │
│          │           │       │        │
│       hash1(x)    hash2(x) hash3(x)   │
└───────────────────────────────────────┘

Check "/items/999":
  - hash1 → bit[2] = 1 ✓
  - hash2 → bit[4] = 1 ✓
  - hash3 → bit[12] = 1 ✓
  → "Probably seen before" → Return cached 404

Check "/items/new":
  - hash1 → bit[7] = 0 ✗
  → "Definitely NOT seen" → Call upstream
```

**Tradeoffs**:
- False positives possible (returns 404 for valid path)
- No false negatives (if bloom says no, it's definitely new)
- Configure `expected_items` and `false_positive_rate` for your use case

---

## Abuse Detection Design

### EWMA (Exponentially Weighted Moving Average)

Tracks rolling request rate, giving more weight to recent values:

```
EWMA_new = α × current_value + (1 - α) × EWMA_old

α = 0.3 (configurable)
Higher α = more responsive to changes
Lower α = more stable/smooth
```

### Z-Score Anomaly Detection

Measures how many standard deviations a value is from the mean:

```
z = (value - mean) / std_dev

If |z| > threshold (default: 3.0):
  → Anomaly detected
  → Apply rate limit multiplier or soft block
```

### Detection Flow

```
Normal Traffic (100 req/min avg)
          │
          ▼
Sudden Spike (500 req/min)
          │
          ▼
Z-Score Calculation: z = (500 - 100) / 50 = 8.0
          │
          ▼
z > 3.0 → ANOMALY DETECTED
          │
          ▼
Action: Soft block for 5 minutes
        Log with reason and score
```

---

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Node.js 18+ (for UI development)
- Python 3.11+ (for API development)

### Local Development

```bash
# Clone and start all services
cd infra
docker-compose up -d --build

# Wait for services to be healthy (about 30 seconds)
docker ps

# Services available at:
# - Gateway API: http://localhost:8000
# - Admin UI: http://localhost:3000
# - Example Upstream: http://localhost:8001
# - PostgreSQL: localhost:5432
# - Redis: localhost:6379
```

### Auto-Seeded Data

The gateway automatically seeds realistic sample data on first startup:

**Tenants:**
- Acme Corporation (E-commerce platform)
- TechFlow Solutions (SaaS analytics)
- CloudBridge Inc (API aggregation)

**Pre-configured API Keys:**
| Key | Tenant | Rate Limit | Daily Quota |
|-----|--------|------------|-------------|
| `hx_prod_acme_7k9m2n4p5q8r1s3t6u0v` | Acme Corporation | 500 RPS | 100,000 |
| `hx_stage_acme_3f5g7h9j2k4l6m8n0p` | Acme (Staging) | 100 RPS | 10,000 |
| `hx_prod_techflow_9a1b3c5d7e2f4g6h8i` | TechFlow | 250 RPS | 50,000 |
| `hx_prod_cloudbridge_5m7n9p1q3r5s7t9u2v` | CloudBridge | 1000 RPS | 200,000 |

**Routes:** `products`, `inventory`, `analytics`, `reports`, `services`, `webhooks`, `demo`

### Verify Setup

```bash
# Check gateway health
curl http://localhost:8000/health

# Test the demo route (use a seeded API key)
curl http://localhost:8000/g/demo/items \
  -H "X-API-Key: hx_prod_acme_7k9m2n4p5q8r1s3t6u0v"

# Open Admin UI and enter admin key: admin-secret-key
# http://localhost:3000
```

---

## Demo Commands

Use the pre-seeded API key: `hx_prod_acme_7k9m2n4p5q8r1s3t6u0v`

### Cache Miss vs Hit

```bash
# First request - Cache MISS (slow, ~2 seconds)
curl -w "\nTime: %{time_total}s\n" \
  http://localhost:8000/g/demo/slow?delay=2 \
  -H "X-API-Key: hx_prod_acme_7k9m2n4p5q8r1s3t6u0v"

# Second request - Cache HIT (instant, ~50ms)
curl -w "\nTime: %{time_total}s\n" \
  http://localhost:8000/g/demo/slow?delay=2 \
  -H "X-API-Key: hx_prod_acme_7k9m2n4p5q8r1s3t6u0v"
```

### SWR Behavior

```bash
# After TTL expires but within stale window:
curl -v http://localhost:8000/g/demo/slow?delay=2 \
  -H "X-API-Key: hx_prod_acme_7k9m2n4p5q8r1s3t6u0v"
# → Instant stale response
# → X-Cache: STALE
# → Background refresh happens automatically
```

### Rate Limiting (PowerShell)

```powershell
# Trigger rate limit (use staging key with 100 RPS limit)
1..200 | ForEach-Object {
  $response = Invoke-WebRequest -Uri "http://localhost:8000/g/demo/items" `
    -Headers @{"X-API-Key"="hx_stage_acme_3f5g7h9j2k4l6m8n0p"} `
    -SkipHttpErrorCheck
  $response.StatusCode
} | Group-Object | Format-Table Name, Count
```

### Rate Limiting (Bash)

```bash
# Trigger rate limit
for i in {1..200}; do
  curl -s -o /dev/null -w "%{http_code}\n" \
    http://localhost:8000/g/demo/items \
    -H "X-API-Key: hx_stage_acme_3f5g7h9j2k4l6m8n0p"
done | sort | uniq -c
```

### Bloom Filter Effect

```bash
# First 404 - hits upstream
curl http://localhost:8000/g/demo/items/nonexistent-product-xyz \
  -H "X-API-Key: hx_prod_acme_7k9m2n4p5q8r1s3t6u0v"
# Check upstream stats
curl http://localhost:8001/stats

# Second 404 - bloom filter prevents upstream call
curl http://localhost:8000/g/demo/items/nonexistent-product-xyz \
  -H "X-API-Key: hx_prod_acme_7k9m2n4p5q8r1s3t6u0v"
# Upstream stats unchanged (no new request)
```

### Compare Gateway vs Upstream Stats

```bash
# Gateway metrics (JSON)
curl http://localhost:8000/metrics

# Gateway metrics (Prometheus format)
curl http://localhost:8000/metrics/prometheus

# Upstream request count
curl http://localhost:8001/stats

# With caching, gateway requests >> upstream requests
```

---

## Deployment

### Step-by-Step Production Deployment

#### 1. Set Up External Services (Free Tier Options)

| Service | Provider | Free Tier | Setup Link |
|---------|----------|-----------|------------|
| PostgreSQL | [Neon](https://neon.tech) | 512MB storage | Sign up, create project |
| PostgreSQL | [Supabase](https://supabase.com) | 500MB storage | Sign up, create project |
| Redis | [Upstash](https://upstash.com) | 10K commands/day | Sign up, create database |
| Redis | [Redis Cloud](https://redis.com) | 30MB | Sign up, create subscription |

#### 2. Deploy Gateway API (Choose One)

**Option A: Render.com**
1. Create a new Web Service
2. Connect your repository
3. Set build command: `cd apps/gateway-api && pip install -r requirements.txt`
4. Set start command: `cd apps/gateway-api && uvicorn src.main:app --host 0.0.0.0 --port $PORT`
5. Add environment variables (see below)

**Option B: Fly.io**
```bash
cd apps/gateway-api
fly launch
fly secrets set DATABASE_URL=... REDIS_URL=... SECRET_KEY=... ADMIN_API_KEY=...
fly deploy
```

**Option C: Railway**
1. New Project → Deploy from GitHub
2. Select `apps/gateway-api` as root directory
3. Add environment variables

#### 3. Deploy Admin UI (Vercel)

```bash
cd ui/admin
vercel
# Set NEXT_PUBLIC_API_URL to your gateway URL
```

Or use Vercel dashboard:
1. Import repository
2. Set root directory to `ui/admin`
3. Add environment variable: `NEXT_PUBLIC_API_URL=https://your-gateway-url`

#### 4. Required Environment Variables

**Gateway API (Required)**:
```bash
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname
REDIS_URL=rediss://default:token@host:6379  # Use rediss:// for TLS
SECRET_KEY=generate-a-32-char-random-string
ADMIN_API_KEY=your-secure-admin-key
CORS_ORIGINS=https://your-admin-ui.vercel.app
AUTO_SEED=true
DEBUG=false
LOG_LEVEL=INFO
```

**Admin UI (Required)**:
```bash
NEXT_PUBLIC_API_URL=https://your-gateway-api.fly.dev
```

**Worker (Optional, for background tasks)**:
```bash
CELERY_BROKER_URL=redis://...
CELERY_RESULT_BACKEND=redis://...
DATABASE_URL=postgresql+asyncpg://...
REDIS_URL=redis://...
```

#### 5. Run Database Migrations

```bash
# Option 1: Via deployed service shell
fly ssh console  # or Render shell
cd apps/gateway-api
alembic upgrade head

# Option 2: Locally with production DATABASE_URL
export DATABASE_URL_SYNC="postgresql://..."
alembic upgrade head
```

### Demo Mode (No Redis Required)

For simple deployments without Redis:

```bash
DEPLOYMENT_MODE=demo
REDIS_URL=  # Leave empty
```

**Demo mode limitations:**
- ✅ In-memory LRU cache with TTL
- ✅ Core gateway functionality works
- ⚠️ No cross-instance cache sharing
- ⚠️ Bloom filter disabled (negative caching unavailable)
- ⚠️ Request coalescing limited to single instance
- ⚠️ SWR refresh via BackgroundTasks (not Celery)

### Docker Compose for Production

```bash
cd infra
docker-compose -f docker-compose.yml up -d

# For demo mode (no Redis)
docker-compose -f docker-compose.demo.yml up -d
```

### Verify Deployment

```bash
# Check health
curl https://your-gateway.fly.dev/health

# Test with seeded API key
curl https://your-gateway.fly.dev/g/demo/items \
  -H "X-API-Key: hx_prod_acme_7k9m2n4p5q8r1s3t6u0v"

# Access Admin UI
# https://your-admin-ui.vercel.app
# Enter your ADMIN_API_KEY in Settings
```

---

## API Reference

### Gateway Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/g/{route}/{path}` | ANY | Proxy to upstream |
| `/health` | GET | Health check |
| `/metrics` | GET | JSON metrics |
| `/metrics/prometheus` | GET | Prometheus format |

### Admin Endpoints

All require `X-Admin-Key` header.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/tenants` | GET, POST | Manage tenants |
| `/admin/tenants/{id}` | GET, PATCH | Tenant details |
| `/admin/keys` | GET, POST | Manage API keys |
| `/admin/keys/{id}` | PATCH, DELETE | Key operations |
| `/admin/keys/{id}/rotate` | POST | Rotate key |
| `/admin/routes` | GET, POST | Manage routes |
| `/admin/routes/{id}` | PATCH, DELETE | Route operations |
| `/admin/policies` | GET, POST | Cache policies |
| `/admin/analytics/summary` | GET | Dashboard stats |
| `/admin/analytics/top-keys` | GET | Top API keys |
| `/admin/analytics/top-routes` | GET | Top routes |
| `/admin/analytics/cache-hit-rate` | GET | Cache stats |
| `/admin/analytics/logs` | GET | Request logs |
| `/admin/cache/purge` | POST | Purge cache |
| `/admin/abuse/blocked` | GET | Blocked keys |
| `/admin/abuse/unblock/{key_id}` | POST | Unblock key |

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | - | PostgreSQL async URL |
| `REDIS_URL` | - | Redis URL (empty = demo mode) |
| `SECRET_KEY` | - | Application secret |
| `ADMIN_API_KEY` | - | Admin authentication key |
| `DEBUG` | false | Enable debug mode |
| `LOG_LEVEL` | INFO | Logging level |
| `DEFAULT_RATE_LIMIT_RPS` | 100 | Default rate limit |
| `DEFAULT_RATE_LIMIT_BURST` | 200 | Default burst size |
| `ABUSE_EWMA_ALPHA` | 0.3 | EWMA smoothing factor |
| `ABUSE_ZSCORE_THRESHOLD` | 3.0 | Anomaly detection threshold |
| `ABUSE_BLOCK_DURATION_SECONDS` | 300 | Soft block duration |
| `BLOOM_EXPECTED_ITEMS` | 10000 | Bloom filter size |
| `BLOOM_FALSE_POSITIVE_RATE` | 0.01 | Bloom filter FP rate |

---

## Development

### Running Tests

```bash
cd apps/gateway-api
pip install -e ".[dev]"
pytest tests/ -v
```

### Database Migrations

```bash
cd apps/gateway-api
alembic upgrade head
```

### Code Quality

```bash
# Linting
ruff check .

# Type checking
mypy src/
```

---

## Limitations

1. **Demo Mode**: No cross-instance cache sharing without Redis
2. **Bloom Filter**: False positives possible - tune `false_positive_rate`
3. **Request Coalescing**: In-process only without Redis pub/sub
4. **Log Retention**: Implement cleanup job for production
5. **Horizontal Scaling**: Requires sticky sessions or Redis pub/sub for full coalescing

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Contributing

Contributions welcome! Please read our contributing guidelines first.

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Run tests
5. Submit a pull request
