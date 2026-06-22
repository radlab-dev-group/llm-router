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
| **Key Generator**     | `core/auth/key_generator.py`   | Generate keys in `sk-litm-` format          |
| **Audit Bridge**      | `core/auth/audit.py`           | Bridge auth events → AnyRequestAuditor      |
| **Metrics**           | `core/auth/metrics.py`         | Prometheus counters & histograms for auth   |
| **Middleware**        | `core/auth/middleware.py`      | Flask before_request hook                   |

---

## Environment Variables

### Core Switch

| Variable                    | Default  | Description                                      |
|-----------------------------|----------|--------------------------------------------------|
| `LLM_ROUTER_AUTH_ENABLED`   | `false`  | Master switch — `"true"` enables all auth        |
| `LLM_ROUTER_AUTH_KEY_STORE` | `memory` | Key store backend: `vault`, `redis`, or `memory` |

### Memory Store

| Variable                           | Default                   | Description                           |
|------------------------------------|---------------------------|---------------------------------------|
| `LLM_ROUTER_AUTH_MEMORY_SEED_FILE` | `~/.llm-router/keys.json` | JSON file with pre-loaded key records |

### Vault Backend

| Variable                            | Default                           | Description                                         |
|-------------------------------------|-----------------------------------|-----------------------------------------------------|
| `LLM_ROUTER_AUTH_VAULT_ADDR`        | *(empty)*                         | Vault server URL (e.g. `https://vault.example.com`) |
| `LLM_ROUTER_AUTH_VAULT_PATH`        | `secret/data/llm-router/api-keys` | KV v2 mount path for key storage                    |
| `LLM_ROUTER_AUTH_VAULT_AUTH_METHOD` | `kubernetes`                      | Auth method: `kubernetes`, `approle`, or `token`    |
| `LLM_ROUTER_AUTH_VAULT_ROLE_ID`     | *(empty)*                         | AppRole role ID (or K8s SA token for K8s auth)      |
| `LLM_ROUTER_AUTH_VAULT_SECRET_ID`   | *(empty)*                         | AppRole secret ID                                   |
| `LLM_ROUTER_AUTH_VAULT_TOKEN`       | *(empty)*                         | Vault token (for token auth)                        |

### Redis Cache

| Variable                           | Default | Description                             |
|------------------------------------|---------|-----------------------------------------|
| `LLM_ROUTER_AUTH_KEY_CACHE_TTL`    | `300`   | Key cache TTL in seconds                |
| `LLM_ROUTER_AUTH_KEY_CACHE_JITTER` | `60`    | Random jitter to prevent cache stampede |

### Rate Limiting

| Variable                             | Default | Description                              |
|--------------------------------------|---------|------------------------------------------|
| `LLM_ROUTER_AUTH_RATE_LIMIT_ENABLED` | `false` | Enable rate limiting                     |
| `LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT` | `60`    | Default rate limit (requests per minute) |

### Public Endpoints

| Variable                           | Default                    | Description                            |
|------------------------------------|----------------------------|----------------------------------------|
| `LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS` | `/ping,/version,/models,/` | Comma-separated paths that bypass auth |

### Key Generation

| Variable                     | Default   | Description                                          |
|------------------------------|-----------|------------------------------------------------------|
| `LLM_ROUTER_AUTH_KEY_PREFIX` | `sk-litm` | Key prefix (like LiteLLM/OpenAI)                     |
| `LLM_ROUTER_AUTH_KEY_LENGTH` | `48`      | Entropy bytes for key generation (produces 64 chars) |

### Key Rotation

| Variable                                | Default | Description                                                |
|-----------------------------------------|---------|------------------------------------------------------------|
| `LLM_ROUTER_AUTH_ROTATION_GRACE_PERIOD` | `3600`  | Old keys remain valid for this many seconds after rotation |

### Audit

| Variable                | Default | Description                         |
|-------------------------|---------|-------------------------------------|
| `LLM_ROUTER_AUTH_AUDIT` | `false` | Record auth events in the audit log |

---

## CLI Commands

### Key Management

```bash
# Generate a new key (persists to seed file when --store memory)
llm-router auth key generate --policy developer --store memory

# List all keys
llm-router auth key list --store memory

# List with plaintext keys visible
llm-router auth key list --store memory --reveal

# Delete a key
llm-router auth key delete key-id

# Rotate a key (old key stays valid for grace_period)
llm-router auth key rotate key-id --grace 3600

# Reveal plaintext key (only in memory store)
llm-router auth key reveal key-id
```

### Policy Management

```bash
# List builtin policies
llm-router auth policy list

# Create a new policy
llm-router auth policy create my-team '{"can_access": true, "rate_limit": 120}'
```

---

## Seed File (Memory Store)

When using `--store memory`, keys are stored in process memory — they are **lost on restart**. To persist keys across
restarts (and between the CLI and router processes), use a seed file.

### Seed File Format

The seed file is a JSON array. Each record must have `key_plain` and optionally `policy_name`, `is_active`,`expires_at`,
`created_at`, `metadata`, and `key_id`.

```json
[
  {
    "key_plain": "sk-litm-my-key-1234567890abcdefghij",
    "policy_name": "developer",
    "is_active": true,
    "expires_at": null,
    "created_at": 1718000000,
    "metadata": {},
    "key_id": "manual-key-001"
  },
  {
    "key_plain": "sk-litm-my-readonly-key-0987654321zyxwvutsrq",
    "policy_name": "readonly",
    "is_active": true,
    "expires_at": 1750000000,
    "created_at": 1718000000,
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

`~/.llm-router/keys.json` (configurable via `LLM_ROUTER_AUTH_MEMORY_SEED_FILE`)

---

## Permission Engine

The permission engine resolves `key → policy → endpoint permissions`:

1. **Public endpoints** — always bypass auth (health checks, version, etc.)
2. **Key authentication** — bcrypt hash lookup in key store
3. **Key validity** — check expiry, rotation, grace period
4. **Policy resolution** — named policy or inline override
5. **Endpoint permission** — per-endpoint + per-model check
6. **Rate limit** — sliding window check per key+IP

### Builtin Policies

| Policy      | Access      | Description                          |
|-------------|-------------|--------------------------------------|
| `developer` | All         | Full access to all endpoints         |
| `admin`     | All         | Admin access                         |
| `chat`      | Chat        | Chat completion endpoints            |
| `embedding` | Embedding   | Embedding endpoints                  |
| `anthropic` | Anthropic   | Anthropic messages endpoint          |
| `ollama`    | Ollama      | Ollama endpoints                     |
| `builtin`   | All builtin | Built-in endpoints (translate, etc.) |

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

Generated keys follow the `sk-litm-<base62>` format:

```
sk-litm-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789abcdefABCDEF123456789
```

- **Prefix**: `sk-litm-` (configurable via `LLM_ROUTER_AUTH_KEY_PREFIX`)
- **Entropy**: 48 bytes cryptographically random (configurable via `LLM_ROUTER_AUTH_KEY_LENGTH`)
- **Charset**: base62 (a-zA-Z0-9)

---

## Deployment Options

Choose a key store backend based on your deployment environment. Each option is documented below with full environment
configuration, key management commands, and operational notes.

### 1️⃣ In-Memory Store — Development / Quick Start

**Use when:** You want to try auth quickly, run locally, or have a single-process deployment.

**Pros:** Zero external dependencies, instant setup. Seed file provides persistence across restarts.
**Cons:** Still per-process — not multi-process safe even with seed file.

```bash
# 1. Create seed file (keys persist to disk)
mkdir -p ~/.llm-router
cat > ~/.llm-router/keys.json << 'EOF'
[
  { "key_plain": "sk-litm-my-dev-key", "policy_name": "developer" }
]
EOF

# 2. Set environment variables
export LLM_ROUTER_AUTH_ENABLED=true
export LLM_ROUTER_AUTH_KEY_STORE=memory
export LLM_ROUTER_AUTH_MEMORY_SEED_FILE=~/.llm-router/keys.json

# 3. Verify keys are loaded
llm-router auth key list --store memory --reveal

# 4. Generate more keys (auto-persisted to seed file)
llm-router auth key generate --policy readonly --store memory

# 5. Run router (keys loaded automatically from seed file)
python -m llm_router_api.rest_api

# 6. Use the key
curl -H "x-api-key: sk-litm-my-dev-key" https://host/api/chat/completions
```

| Variable                           | Value                                                       |
|------------------------------------|-------------------------------------------------------------|
| `LLM_ROUTER_AUTH_ENABLED`          | `true`                                                      |
| `LLM_ROUTER_AUTH_KEY_STORE`        | `memory`                                                    |
| `LLM_ROUTER_AUTH_MEMORY_SEED_FILE` | Path to seed JSON file (default: `~/.llm-router/keys.json`) |

**Operational notes:**

- Seed file auto-updates after `generate`, `delete`, and `rotate`.
- Keys are visible to both CLI and router via the same seed file.
- Suitable for development, CI, and single-node deployments.
- No Redis or Vault required.

---

### 2️⃣ Redis Store — Multi-Process / Stateful Single-Node

**Use when:** You run multiple workers/processes and need persistent key storage without Vault.

**Pros:** Persistent keys across restarts (if Redis is durable), multi-process safe.
**Cons:** Requires Redis instance. No encryption-at-rest (use TLS for production).

```bash
# 1. Start Redis
redis-server

# 2. Set environment variables
export LLM_ROUTER_AUTH_ENABLED=true
export LLM_ROUTER_AUTH_KEY_STORE=redis
export LLM_ROUTER_REDIS_HOST=127.0.0.1
export LLM_ROUTER_REDIS_PORT=6379
export LLM_ROUTER_REDIS_DB=0
# export LLM_ROUTER_REDIS_PASSWORD=secret  # if Redis requires auth

# 3. Generate keys (written to Redis)
llm-router auth key generate --policy developer --store redis
llm-router auth key list --store redis

# 4. Run router (reads keys from same Redis instance)
python -m llm_router_api.rest_api

# 5. Use the key
curl -H "x-api-key: sk-litm-..." https://host/api/chat/completions
```

| Variable                    | Value                            |
|-----------------------------|----------------------------------|
| `LLM_ROUTER_AUTH_ENABLED`   | `true`                           |
| `LLM_ROUTER_AUTH_KEY_STORE` | `redis`                          |
| `LLM_ROUTER_REDIS_HOST`     | Redis host (default `127.0.0.1`) |
| `LLM_ROUTER_REDIS_PORT`     | Redis port (default `6379`)      |
| `LLM_ROUTER_REDIS_DB`       | Redis DB number (default `0`)    |
| `LLM_ROUTER_REDIS_PASSWORD` | Redis password (default: none)   |

**Operational notes:**

- Keys stored in Redis hashes under `secret:llm-router:api-keys:<key_id>`.
- Works across multiple Flask workers — all workers see the same key set.
- Redis is already required for load balancing (same instance works).
- For production, use Redis Sentinel or a managed Redis service with TLS.

---

### 3️⃣ HashiCorp Vault — Production / Multi-Cluster / Enterprise

**Use when:** You need enterprise-grade key management, secret rotation, or multi-cluster consistency.

**Pros:** Centralized key management, encryption, RBAC, audit logging.
**Cons:** Requires Vault infrastructure and auth method configuration.

#### 3a. Kubernetes Auth (recommended for K8s deployments)

```bash
# 1. Set environment variables
export LLM_ROUTER_AUTH_ENABLED=true
export LLM_ROUTER_AUTH_KEY_STORE=vault
export LLM_ROUTER_AUTH_VAULT_ADDR=https://vault.example.com
export LLM_ROUTER_AUTH_VAULT_PATH=secret/data/llm-router/api-keys
export LLM_ROUTER_AUTH_VAULT_AUTH_METHOD=kubernetes

# Vault will auto-detect the Kubernetes service account token
# at /var/run/secrets/kubernetes.io/serviceaccount/token

# 2. Generate and use keys
llm-router auth key generate --policy developer --store vault
llm-router auth key list --store vault
curl -H "x-api-key: sk-litm-..." https://host/api/chat/completions
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
- Vault auto-deletes keys after rotation if configured.
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

| Feature                 | Memory (+seed)    | Redis                       | Vault (K8s)          | Vault (AppRole)       |
|-------------------------|-------------------|-----------------------------|----------------------|-----------------------|
| **Persistence**         | ✅ Yes (seed file) | ✅ Yes (RDB/AOF)             | ✅ Yes                | ✅ Yes                 |
| **Multi-process safe**  | ❌ No              | ✅ Yes                       | ✅ Yes                | ✅ Yes                 |
| **Encryption-at-rest**  | ❌ No              | ✅ Yes (if Redis configured) | ✅ Yes (Vault native) | ✅ Yes (Vault native)  |
| **Secret rotation**     | Manual            | Manual                      | ✅ Automatic + manual | ✅ Automatic + manual  |
| **External dependency** | None              | Redis                       | Vault + K8s SA token | Vault + AppRole creds |
| **Production ready**    | ❌ Dev only        | ✅ Yes                       | ✅ Yes                | ✅ Yes                 |
| **Audit logging**       | ❌ No              | ❌ No                        | ✅ Yes (Vault audit)  | ✅ Yes (Vault audit)   |

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
- **[Auditing subsystem](core/auditor/README.md)** — tamper-evident audit logging
