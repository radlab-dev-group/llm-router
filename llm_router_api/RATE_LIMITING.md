# Rate Limiting

Sliding-window rate limiting backed by Redis sorted sets. Prevents API abuse, controls load on downstream LLM providers,
and protects against brute-force key enumeration.

---

## How It Works

### Sliding Window Algorithm

The rate limiter uses a **sliding window** approach — unlike fixed-window counters, there are no boundary spikes. Each
request timestamp is stored as a member score in a Redis sorted set, and entries older than the window are purged on
every check.

```
Time → ──────────────────────────────────────────▶
       │<────── WINDOW (60s) ──────▶│
       ▼                             ▼
       │  ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉         │
       │ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉ ◉      │
       │                            │
       ←─ remaining slots ────────→
```

- **Precision:** per-request, no fixed-boundary artifacts
- **Memory:** O(requests per key+IP) — old entries are automatically purged
- **Durability:** Redis persistence (RDB/AOF) protects against server restart

### Key + IP Binning

Rate limits are enforced **per API key + client IP**. This means:

- Each API key gets its own independent quota
- Multiple IPs sharing the same key share that key's quota
- A malicious IP hitting a leaked key can exhaust its quota (mitigated by IP-level monitoring)

### Bucket Naming

```
auth:ratelimit:{key_id}:{ip}
```

Example: `auth:ratelimit:dev-a1b2c3d3:192.168.1.100`

---

## Configuration

### Environment Variables

| Variable                             | Default  | Description                                                   |
|--------------------------------------|----------|---------------------------------------------------------------|
| `LLM_ROUTER_AUTH_RATE_LIMIT_ENABLED` | `false`  | Enable rate limiting                                          |
| `LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT` | `60`     | Default rate limit (requests per minute)                      |
| `LLM_ROUTER_AUTH_KEY_STORE`          | `memory` | Key store backend (Redis store recommended for rate limiting) |

### Enabling Rate Limiting

```bash
export LLM_ROUTER_AUTH_ENABLED=true
export LLM_ROUTER_AUTH_RATE_LIMIT_ENABLED=true
export LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT=60  # 60 requests per minute per key
python -m llm_router_api.rest_api
```

---

## Response Behavior

When a request exceeds the rate limit, the router returns:

| HTTP Status             | Header        | Value                                                  |
|-------------------------|---------------|--------------------------------------------------------|
| `429 Too Many Requests` | `Retry-After` | Seconds until the oldest request in the window expires |

Example:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 35

{"error": {"message": "Rate limit exceeded"}}
```

The `Retry-After` value is calculated from the oldest entry still in the window — this tells the client exactly when it
can retry.

---

## Architecture

```
Client Request → AuthMiddleware
               → get_auth_result()
               → RedisRateLimiter.is_allowed(key_id, ip, limit)
               → → Redis sorted set operations (zremrangebyscore, zcard, zadd, expire)
               → RateLimitResult(allowed, remaining, retry_after)
               → If denied: HTTP 429
               → If allowed: continue to endpoint
```

### `RateLimitResult` Dataclass

```python
@dataclass
class RateLimitResult:
    allowed: bool  # Whether the request is within the limit
    remaining: int  # Remaining requests in the current window
    retry_after: int  # Seconds until the oldest request expires (0 if allowed)
```

### `RedisRateLimiter` Class

```python
class RedisRateLimiter:
    PREFIX = "auth:ratelimit"
    WINDOW = 60  # seconds

    def __init__(
            self,
            redis_client: redis.Redis | None = None,
            redis_host: str | None = None,
            redis_port: int = 6379,
            redis_db: int = 0,
            redis_password: str | None = None,
            window: int = 60,
    )

    def is_allowed(self, key_id: str, ip: str, limit: int) -> RateLimitResult
```

---

## Prometheus Metrics

When `LLM_ROUTER_USE_PROMETHEUS=true`, the rate limiter exposes:

| Metric                      | Type    | Labels               | Description             |
|-----------------------------|---------|----------------------|-------------------------|
| `rate_limit_exceeded_total` | Counter | `key_id`, `endpoint` | Total rate limit events |

---

## Rate Limit Strategy by Use Case

### Per-User Quotas (Default)

Each API key gets `LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT` requests per minute:

```bash
export LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT=60  # 1 req/sec
```

**Recommended values:**

| Use Case         | Rate Limit (req/min) | Notes                                |
|------------------|----------------------|--------------------------------------|
| Internal tools   | 120–300              | Higher for development               |
| Production apps  | 60                   | 1 req/sec standard                   |
| Batch processing | 30                   | 0.5 req/sec to avoid provider limits |
| User-facing APIs | 30–60                | Vary by user tier                    |

### Tiered Rate Limiting (Policy-Based)

Higher-tier users can get increased limits via policy override:

```bash
# Developer tier (default)
export LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT=60

# Admin tier (can be configured per-key)
# In seed file:
#   "policy_override": { "rate_limit": 300 }
```

---

## Redis Requirements

**Redis is required** when rate limiting is enabled. The rate limiter stores state in Redis sorted sets:

- **Memory usage:** ~100 bytes per entry (score + member + set overhead)
- **At 60 req/min per key:** ~60 entries per bucket × ~100 bytes = ~6 KB per key
- **At 1000 keys:** ~6 MB total

### Redis Persistence

For production, enable Redis persistence to protect rate limit state:

```bash
# RDB snapshots (recommended)
save 900 1
save 300 10
save 60 10000

# Or AOF (more durable but higher I/O)
appendonly yes
appendfsync everysec
```

---

## Comparison with Fixed-Window

| Feature          | Sliding Window (current) | Fixed Window                      |
|------------------|--------------------------|-----------------------------------|
| Boundary spikes  | ❌ No                     | ✅ Yes                             |
| Precision        | Per-request              | Per-window                        |
| Memory           | O(entries)               | O(windows)                        |
| Burst protection | ✅ Excellent              | ⚠️ Can allow 2× limit at boundary |

### Why Sliding Window?

1. **No boundary spikes:** A user at 00:59 and 01:01 sees a full window in fixed-window; sliding window sees the true
   request rate
2. **Better burst protection:** Truly limits sustained abuse, not just window-averaged abuse
3. **Predictable behavior:** `Retry-After` is accurate because it's based on the oldest actual entry

---

## Best Practices

### 1. Always Enable Rate Limiting in Production

```bash
export LLM_ROUTER_AUTH_RATE_LIMIT_ENABLED=true
```

Without it, a leaked API key allows unlimited requests to your downstream providers.

### 2. Use Redis Store for Key Management

```bash
export LLM_ROUTER_AUTH_KEY_STORE=redis
```

Rate limit state is already in Redis — using Redis for keys keeps state co-located.

### 3. Monitor Rate Limit Events

Check Prometheus:

```
sum(rate(rate_limit_exceeded_total[5m])) by (key_id)
```

High rates indicate:

- Leaked API keys (immediate rotation required)
- Misconfigured clients (exponential backoff needed)
- Intentional abuse (block the key)

### 4. Set Graceful Limits

```bash
# Generous for dev, strict for prod
export LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT=60  # prod: 1 req/sec
```

### 5. Use Public Endpoints for Health Checks

Health checks should not count against rate limits:

```bash
export LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS="/ping,/version,/models,/,/health"
```

---

## Migration from No-Limit

**Before (no rate limiting):**

```bash
export LLM_ROUTER_AUTH_ENABLED=true
export LLM_ROUTER_AUTH_RATE_LIMIT_ENABLED=false  # or unset
```

**After (with rate limiting):**

```bash
export LLM_ROUTER_AUTH_ENABLED=true
export LLM_ROUTER_AUTH_RATE_LIMIT_ENABLED=true
export LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT=60
```

**Expected impact:**

- Clients must implement retry logic with exponential backoff
- Monitor Prometheus for 429 responses in the first 24 hours
- Adjust `LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT` based on observed needs

---

## Troubleshooting

### "Why am I getting 429s immediately?"

1. Check if the key has been rotated (old key may have accumulated requests)
2. Verify the rate limit value: `LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT`
3. Check Prometheus for rate limit events: `rate_limit_exceeded_total`

### "Rate limit is too strict/loose"

- **Too strict:** Increase `LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT`
- **Too loose:** Decrease the value or add per-key overrides via seed file

### "Clients aren't respecting Retry-After"

Most HTTP clients support automatic retry with `Retry-After`. Check your client library:

- **Python `requests`:** Use `tenacity` or `backoff` library
- **Go `http.Client`:** Implement retry logic with `Retry-After` header
- **JavaScript `fetch`:** Parse `Retry-After` header and use `setTimeout`

---

## See Also

- **[Authentication documentation](AUTHENTICATION.md)** — full auth setup, key management, and seed files
- **[Prometheus metrics](AUTHENTICATION.md#prometheus-metrics)** — monitor rate limits and auth events
