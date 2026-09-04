# Authentication & Authorization

API-key-based authentication with per-endpoint policies, rate limiting, audit trail, and Prometheus metrics.

**Enabled by default: `LLM_ROUTER_AUTH_ENABLED=false`** — set to `"true"` to enforce authentication.

---

## Architecture

```
Client Request → AuthMiddleware → Key Store Lookup → Permission Engine → Rate Limiter → Endpoint
               → Audit Bridge → AnyRequestAuditor
               → AuthMetrics → Prometheus
```

### Components

| Component             | Module                         | Purpose                                     |
|-----------------------|--------------------------------|---------------------------------------------|
| **Key Store**         | `core/auth/key_store/`         | Vault, Redis, or in-memory key storage      |
| **Permission Engine** | `core/auth/policies/engine.py` | Resolve key → policy → endpoint permissions |
| **Rate Limiter**      | `core/auth/rate_limiter.py`    | Redis-backed sliding window rate limiter    |
| **Key Generator**     | `core/auth/key_generator.py`   | Generate keys in `sk-llmr-live-` format     |
| **Audit Bridge**      | `core/auth/audit.py`           | Bridge auth events → AnyRequestAuditor      |
| **Metrics**           | `core/auth/metrics.py`         | Prometheus counters & histograms for auth   |
| **Middleware**        | `core/auth/middleware.py`      | Flask before_request hook                   |

---

## Environment Variables

All environment variables are documented in **[ENV_DEFINITIONS.md](./ENV_DEFINITIONS.md)**. Auth-specific vars start
with `LLM_ROUTER_AUTH_*`.

---

## CLI Commands

### Key Management

```bash
# Generate a new key (persists to seed file when --store memory)
llm-router auth key generate --policy developer --store memory

# List all keys
llm-router auth key list --store memory

# Delete a key
llm-router auth key delete key-id

# Disable a key (revokes access immediately)
llm-router auth key disable key-id [--store memory]

# Enable a previously disabled key
llm-router auth key enable key-id [--store memory]

# Rotate a key (old key stays valid for grace_period)
llm-router auth key rotate key-id --grace 3600
```

### Policy Management

```bash
# List builtin policies (custom ones are marked with "(custom)")
llm-router auth policy list

# Create a new policy — inline JSON, from a file, or from stdin (-)
llm-router auth policy create my-team '{"can_access": true, "rate_limit": 120}'
llm-router auth policy create my-team --file my-team.json
cat my-team.json | llm-router auth policy create my-team --file -
```

> Custom policies are persisted to `$LLM_ROUTER_AUTH_CUSTOM_POLICIES_FILE`
> (default: `~/.llm-router/configs/auth/custom-policies.json`) and resolved by
> the server without a restart.

### Rate Limit

```bash
# List available rate-limit presets
llm-router auth rate-limit list

# Apply a rate-limit preset to an existing key
llm-router auth rate-limit apply key-id --preset pro

# Remove rate-limit override from a key (revert to global default)
llm-router auth rate-limit remove key-id
```

---

## Seed File (Memory Store)

When using `--store memory`, keys are stored in process memory — they are **lost on restart**. To persist keys across
restarts (and between the CLI and router processes), use a seed file.

### Seed File Format

The seed file is a JSON array. Each record must carry a verifiable credential:
a `key_hash` (+`key_index`) pair, or — for legacy files only — a `key_plain`
which is **hashed at load time and never written back**. Plaintext keys are never persisted.

| Field             | Type    | Description                                                     |
|-------------------|---------|-----------------------------------------------------------------|
| `key_id`          | `str`   | Unique identifier for this key                                  |
| `key_hash`        | `str`   | bcrypt hash of the plaintext key (the verifiable credential)    |
| `key_index`       | `str`   | SHA-256 of the plaintext key — O(1) lookup index (locator only) |
| `key_prefix`      | `str`   | First 7 characters of the plaintext key (for display only)      |
| `policy_name`     | `str`   | Name of the default policy to apply                             |
| `policy_override` | `dict`  | Inline policy override (takes precedence over the named policy) |
| `is_active`       | `bool`  | Whether the key is currently valid                              |
| `expires_at`      | `float` | Expiry timestamp (`null` = no expiry)                           |
| `created_at`      | `float` | Unix timestamp of key creation (auto-generated if omitted)      |
| `last_used_at`    | `float` | Last successful authentication time                             |
| `rotate_at`       | `float` | Scheduled rotation time                                         |
| `grace_until`     | `float` | Key remains valid until this time after rotation                |
| `metadata`        | `dict`  | Arbitrary metadata (team, cost_center, etc.)                    |

```json
[
  {
    "key_id": "manual-key-001",
    "key_hash": "$2b$12$Kx7Q2m...bcrypt-hash.../",
    "key_index": "9f2c...sha256-hex...",
    "key_prefix": "sk-llmr-live",
    "policy_name": "developer",
    "is_active": true,
    "expires_at": null,
    "created_at": 1718000000,
    "last_used_at": null,
    "rotate_at": null,
    "grace_until": null,
    "metadata": {},
    "policy_override": {
      "rate_limit": 300
    }
  },
  {
    "key_id": "manual-key-002",
    "key_hash": "$2b$12$Pq8W3n...bcrypt-hash.../",
    "key_index": "1a4d...sha256-hex...",
    "key_prefix": "sk-llmr-live",
    "policy_name": "chat",
    "is_active": true,
    "expires_at": 1750000000,
    "created_at": 1718000000,
    "last_used_at": null,
    "rotate_at": null,
    "grace_until": null,
    "metadata": {
      "team": "backend"
    }
  }
]
```

### How It Works

- **On router startup**: `MemoryKeyStore` reads the seed file and loads all keys into memory.
- **After CLI key operations**: `generate`, `delete`, and `rotate` automatically write back to the seed file.
- **No restart needed**: Changes made via CLI are visible to the router on the next request (the router reloads the seed
  file on each request via the middleware).

### Default Location

`~/.llm-router/configs/auth/memory-keys.json`

---

## Permission Engine

The permission engine resolves `key → policy → endpoint permissions`. Authorization is **default-deny**: an endpoint is
reachable only if the key's policy explicitly grants the endpoint's permission *type*.

1. **Public endpoints** — always bypass auth (health checks, version, etc.)
2. **Key authentication** — O (1) SHA-256 index lookup + constant-time `bcrypt.checkpw`
3. **Key validity** — check active flag, expiry, rotation, grace period
4. **Policy resolution** — named policy or inline override (an unknown policy name grants *nothing*)
5. **Type gate** — the endpoint's required type (e.g. `chat`, `embedding`)
   must be in the policy's `allowed_types`
6. **IP whitelist** — if the policy sets `ip_whitelist`, the client IP (resolved per `LLM_ROUTER_TRUSTED_PROXIES`) must
   match
7. **Token budget** — if the policy sets `budget_monthly_tokens`, usage must be below it
8. **Endpoint permission** — per-endpoint + per-model refinement
9. **Rate limit** — sliding window check per key+IP

### Builtin Policies

| Policy      | Access    | Description                          |
|-------------|-----------|--------------------------------------|
| `developer` | All types | Full access to all endpoint types    |
| `admin`     | All types | Admin access                         |
| `chat`      | Chat      | Chat completion endpoints            |
| `embedding` | Embedding | Embedding endpoints                  |
| `anthropic` | Anthropic | Anthropic messages endpoint          |
| `ollama`    | Ollama    | Ollama endpoints                     |
| `builtin`   | Builtin   | Built-in endpoints (translate, etc.) |

> **Note (breaking):** a policy with an empty/missing `allowed_types` grants
> no access. Existing keys on `developer`/`admin` are unaffected; keys with
> custom policies should be checked against their endpoint needs.

---

## Prometheus Metrics

Auth metrics are registered when `LLM_ROUTER_USE_PROMETHEUS=true`:

| Metric                      | Type      | Labels                   | Description                   |
|-----------------------------|-----------|--------------------------|-------------------------------|
| `auth_attempts_total`       | Counter   | `result`, `key_id`       | Total auth attempts by result |
| `auth_latency_seconds`      | Histogram | `step`                   | Latency per auth step         |
| `rate_limit_exceeded_total` | Counter   | `key_id`, `endpoint`     | Rate limit events             |
| `key_budget_usage_tokens`   | Gauge     | `key_id`, `budget_total` | Token budget usage            |

---

## Key Format

Generated keys follow the `sk-llmr-live-<base62>` format:

```
sk-llmr-live-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789abcdefABCDEF123456789
```

- **Prefix**: `sk-llmr-live-` (configurable via `LLM_ROUTER_AUTH_KEY_PREFIX`)
- **Entropy**: 48 bytes cryptographically random (configurable via `LLM_ROUTER_AUTH_KEY_LENGTH`)
- **Charset**: base62 (a-zA-Z0-9)

---

## Deployment Options

Choose a key store backend based on your deployment environment. Each option is documented below with full environment
configuration, key management commands, and operational notes.

### 1️⃣ In-Memory Store — Development / Quick Start

**Use when:** You want to try auth quickly, run locally, or have a single-process deployment.

**Pros:** Zero external dependencies, instant setup. Seed file provides persistence across restarts. **Cons:** Still
per-process — not multi-process safe even with seed file.

```bash
# 1. Create seed file (keys persist to disk)
mkdir -p ~/.llm-router/configs/auth
cat > ~/.llm-router/configs/auth/memory-keys.json << 'EOF'
[
  { "key_plain": "sk-llmr-live-my-dev-key", "policy_name": "developer" }
]
EOF

# 2. Set environment variables
export LLM_ROUTER_AUTH_ENABLED=true
export LLM_ROUTER_AUTH_KEY_STORE=memory

# 3. Verify keys are loaded
llm-router auth key list --store memory --reveal

# 4. Generate more keys (auto-persisted to seed file)
llm-router auth key generate --policy readonly --store memory

# 5. Run router (keys loaded automatically from seed file)
python -m llm_router_api.rest_api

# 6. Use the key
curl -H "x-api-key: sk-llmr-live-my-dev-key" https://host/api/chat/completions
```

| Variable                    | Value    |
|-----------------------------|----------|
| `LLM_ROUTER_AUTH_ENABLED`   | `true`   |
| `LLM_ROUTER_AUTH_KEY_STORE` | `memory` |

**Operational notes:**

- Seed file auto-updates after `generate`, `delete`, and `rotate`.
- Keys are visible to both CLI and router via the same seed file.
- Suitable for development, CI, and single-node deployments.
- No Redis or Vault required.

---

### 2️⃣ Redis Store — Multi-Process / Stateful Single-Node

**Use when:** You run multiple workers/processes and need persistent key storage without Vault.

**Pros:** Persistent keys across restarts (if Redis is durable), multi-process safe. **Cons:** Requires Redis instance.
No encryption-at-rest (use TLS for production).

```bash
# 1. Start Redis
redis-server

# 2. Set environment variables
export LLM_ROUTER_AUTH_ENABLED=true
export LLM_ROUTER_AUTH_KEY_STORE=redis
export LLM_ROUTER_AUTH_REDIS_HOST=127.0.0.1
export LLM_ROUTER_AUTH_REDIS_PORT=6379
export LLM_ROUTER_AUTH_REDIS_DB=0
# export LLM_ROUTER_AUTH_REDIS_PASSWORD=secret  # if Redis requires auth
# export LLM_ROUTER_AUTH_REDIS_PROTOCOL=3  # RESP3 (default) or 2 (RESP2)

# 3. Generate keys (written to Redis)
llm-router auth key generate --policy developer --store redis
llm-router auth key list --store redis

# 4. Run router (reads keys from same Redis instance)
python -m llm_router_api.rest_api

# 5. Use the key
curl -H "x-api-key: sk-llmr-live-..." https://host/api/chat/completions
```

| Variable                         | Value                            |
|----------------------------------|----------------------------------|
| `LLM_ROUTER_AUTH_ENABLED`        | `true`                           |
| `LLM_ROUTER_AUTH_KEY_STORE`      | `redis`                          |
| `LLM_ROUTER_AUTH_REDIS_HOST`     | Redis host (default `127.0.0.1`) |
| `LLM_ROUTER_AUTH_REDIS_PORT`     | Redis port (default `6379`)      |
| `LLM_ROUTER_AUTH_REDIS_DB`       | Redis DB number (default `0`)    |
| `LLM_ROUTER_AUTH_REDIS_PASSWORD` | Redis password (default: none)   |
| `LLM_ROUTER_AUTH_REDIS_PROTOCOL` | Redis protocol (default `3`)     |

**Operational notes:**

- Keys stored as JSON strings in Redis under `secret:llm-router:api-keys:<key_id>`.
- Works across multiple Flask workers — all workers see the same key set.
- Redis is already required for load balancing (same instance works).
- For production, use Redis Sentinel or a managed Redis service with TLS.

---

### 3️⃣ HashiCorp Vault — Production / Multi-Cluster / Enterprise

**Use when:** You need enterprise-grade key management, secret rotation, or multi-cluster consistency.

**Pros:** Centralized key management, encryption, RBAC, audit logging. **Cons:** Requires Vault infrastructure and auth
method configuration.

#### 3a. Kubernetes Auth (recommended for K8s deployments)

```bash
# 1. Set environment variables
export LLM_ROUTER_AUTH_ENABLED=true
export LLM_ROUTER_AUTH_KEY_STORE=vault
export LLM_ROUTER_AUTH_VAULT_ADDR=https://vault.example.com
export LLM_ROUTER_AUTH_VAULT_PATH=secret/data/llm-router/api-keys
export LLM_ROUTER_AUTH_VAULT_AUTH_METHOD=kubernetes

# The K8s service account JWT is read from:
# /var/run/secrets/kubernetes.io/serviceaccount/token (hardcoded)

# 2. Generate and use keys
llm-router auth key generate --policy developer --store vault
llm-router auth key list --store vault
curl -H "x-api-key: sk-llmr-live-..." https://host/api/chat/completions
```

| Variable                            | Value                                                         |
|-------------------------------------|---------------------------------------------------------------|
| `LLM_ROUTER_AUTH_ENABLED`           | `true`                                                        |
| `LLM_ROUTER_AUTH_KEY_STORE`         | `vault`                                                       |
| `LLM_ROUTER_AUTH_VAULT_ADDR`        | Vault server URL                                              |
| `LLM_ROUTER_AUTH_VAULT_PATH`        | KV v2 mount path (default: `secret/data/llm-router/api-keys`) |
| `LLM_ROUTER_AUTH_VAULT_AUTH_METHOD` | `kubernetes`                                                  |
| `LLM_ROUTER_AUTH_VAULT_ROLE_ID`     | (optional) Vault role ID                                      |

**Operational notes:**

- Vault K8s auth reads the service account JWT automatically.
- Keys stored under `{vault_path}/{key_id}/data` in KV v2 format.
- On rotation the old key is deactivated (`is_active=False`) and a new key is written.
- Ensure the Vault Role has `read` and `create` policies for the mount path.

#### 3b. AppRole Auth (non-K8s / VM deployments)

```bash
export LLM_ROUTER_AUTH_ENABLED=true
export LLM_ROUTER_AUTH_KEY_STORE=vault
export LLM_ROUTER_AUTH_VAULT_ADDR=https://vault.example.com
export LLM_ROUTER_AUTH_VAULT_AUTH_METHOD=approle
export LLM_ROUTER_AUTH_VAULT_ROLE_ID=your-approle-role-id
export LLM_ROUTER_AUTH_VAULT_SECRET_ID=your-approle-secret-id
```

#### 3c. Token Auth (manual / CI pipelines)

```bash
export LLM_ROUTER_AUTH_ENABLED=true
export LLM_ROUTER_AUTH_KEY_STORE=vault
export LLM_ROUTER_AUTH_VAULT_ADDR=https://vault.example.com
export LLM_ROUTER_AUTH_VAULT_AUTH_METHOD=token
export LLM_ROUTER_AUTH_VAULT_TOKEN=s.your-vault-token-here
```

**Operational notes:**

- For production, use AppRole or K8s auth — token auth is less secure.
- Vault path is configurable per environment (e.g., `secret/data/llm-router-staging/api-keys`).
- Supports key rotation: `llm-router auth key rotate key-id --grace 3600`.

---

### Comparison Matrix

| Feature                 | Memory (+seed)     | Redis                                                               | Vault (K8s)           | Vault (AppRole)       |
|-------------------------|--------------------|---------------------------------------------------------------------|-----------------------|-----------------------|
| **Persistence**         | ✅ Yes (seed file) | ✅ Yes (RDB/AOF)                                                    | ✅ Yes                | ✅ Yes                |
| **Multi-process safe**  | ❌ No              | ✅ Yes                                                              | ✅ Yes                | ✅ Yes                |
| **Encryption-at-rest**  | ❌ No              | ⚠️ No (app does not configure SSL/TLS — use managed Redis with TLS) | ✅ Yes (Vault native) | ✅ Yes (Vault native) |
| **Secret rotation**     | Manual             | Manual                                                              | ✅ Automatic + manual | ✅ Automatic + manual |
| **External dependency** | None               | Redis                                                               | Vault + K8s SA token  | Vault + AppRole creds |
| **Production ready**    | ❌ Dev only        | ✅ Yes                                                              | ✅ Yes                | ✅ Yes                |
| **Audit logging**       | ❌ No              | ❌ No                                                               | ✅ Yes (Vault audit)  | ✅ Yes (Vault audit)  |

**Recommendation:**

- **Dev / testing:** Use `memory` with seed file (zero setup).
- **Staging / small production:** Use `redis` (already required for load balancing).
- **Multi-cluster / enterprise:** Use `vault` with K8s or AppRole auth.

- Keys are stored as **bcrypt hashes** — plaintext is never persisted in the store
- The plaintext key is returned **only once** at creation time
- Rate limiting prevents brute-force attacks even if key hashes leak
- Audit bridge records all auth events (success, failure, rate limit) for compliance

---

## See Also

- **[Rate Limiting](RATE_LIMITING.md)** — sliding-window rate limiting, configuration, and monitoring
- **[Auditing subsystem](../core/auditor/README.md)** — tamper-evident audit logging
