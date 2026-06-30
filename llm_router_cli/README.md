# llm-router CLI — Command Reference

**Package:** `llm-router` (v0.6.0)
**Entry points:**

- `llm-router` — main CLI tool (auth, anonymizer)
- `llm-router-fast-masker` — deprecated, delegated to `llm-router auth anonymizer run --algorithm fast_masker`

---

## Quick Start

```bash
pip install llm-router[api]
llm-router --help
llm-router --version   # 0.6.0
```

---

## Top-Level Commands

| Command          | Description                                  |
|------------------|----------------------------------------------|
| `auth`           | Manage API keys, policies, and rate limiting |
| `anonymizer run` | Anonymize text using a selectable algorithm  |

---

## `llm-router auth` — API Key & Authentication Management

### Command Tree

```
llm-router auth key <command>          # API key lifecycle
llm-router auth policy <command>       # Policy management
llm-router auth rate-limit <command>   # Per-key rate limit overrides
```

### Shared Flags (all subcommands)

| Flag                    | Default   | Description                              |
|-------------------------|-----------|------------------------------------------|
| `--store <backend>`     | `memory`  | Key store: `memory`, `redis`, or `vault` |
| `--auth-redis-host`     | *(empty)* | Auth Redis host                          |
| `--auth-redis-port`     | `6379`    | Auth Redis port                          |
| `--auth-redis-db`       | `0`       | Auth Redis database number               |
| `--auth-redis-password` | —         | Auth Redis password                      |

> **Note:** These auth-specific Redis flags are separate from general `LLM_ROUTER_REDIS_*` env vars.

---

### Key Management: `llm-router auth key <command>`

#### `generate` — Create a new API key

```bash
llm-router auth key generate \
  --policy developer \
  --expires 1750000000 \
  --store memory
```

| Flag        | Default     | Description                       |
|-------------|-------------|-----------------------------------|
| `--policy`  | `developer` | Policy name to assign             |
| `--expires` | `None`      | Expiry (Unix timestamp or `None`) |
| `--output`  | *(stdout)*  | Output file path                  |

Output: `sk-litm-<base62>` key (plaintext shown **once** at creation).

#### `list` — List all API keys

```bash
llm-router auth key list --store memory [--reveal] [--json]
```

| Flag       | Default | Description                             |
|------------|---------|-----------------------------------------|
| `--json`   | `false` | Output in JSON format                   |
| `--reveal` | `false` | Show plaintext keys (memory store only) |

#### `delete <key-id>` — Delete a key permanently

```bash
llm-router auth key delete <key-id> --store memory
```

#### `disable <key-id>` — Deactivate without deleting

```bash
llm-router auth key disable <key-id> [--store memory]
```

#### `enable <key-id>` — Re-activate a disabled key

```bash
llm-router auth key enable <key-id> [--store memory]
```

#### `rotate <key-id>` — Generate a replacement key

```bash
llm-router auth key rotate <key-id> --grace 3600 [--store memory]
```

| Flag      | Default | Description                                   |
|-----------|---------|-----------------------------------------------|
| `--grace` | `3600`  | Grace period in seconds (old key stays valid) |

#### `reveal <key-id>` — Show plaintext key

```bash
llm-router auth key reveal <key-id> [--store memory]
```

Only available for the **memory** store.

---

### Policy Management: `llm-router auth policy <command>`

#### `list` — List builtin policies

```bash
llm-router auth policy list
```

**Builtin policies:**

| Policy      | Access      | Description                          |
|-------------|-------------|--------------------------------------|
| `developer` | All         | Full access to all endpoints         |
| `admin`     | All         | Admin access                         |
| `chat`      | Chat        | Chat completion endpoints            |
| `embedding` | Embedding   | Embedding endpoints                  |
| `anthropic` | Anthropic   | Anthropic messages endpoint          |
| `ollama`    | Ollama      | Ollama endpoints                     |
| `builtin`   | All builtin | Built-in endpoints (translate, etc.) |

#### `create <name> <json-policy>` — Register a custom policy

```bash
llm-router auth policy create my-team '{
  "can_access": true,
  "rate_limit": 120,
  "model_whitelist": ["gpt-4", "llama-3"]
}' --store memory
```

---

### Rate Limit Overrides: `llm-router auth rate-limit <command>`

> **Note:** Rate limiting is always active when authentication is enabled. These commands manage **per-key overrides**
> on top of the default policy rate limit (60 rpm).

#### `list` — Show available presets

```bash
llm-router auth rate-limit list
```

#### `apply <key-id> --preset <name>` — Set a per-key rate limit via preset

```bash
llm-router auth rate-limit apply <key-id> --preset pro --store memory
```

**Available presets:**

| Preset          | RPM | Daily Limit | Per-Second | Description                      |
|-----------------|-----|-------------|------------|----------------------------------|
| `free`          | 10  | —           | —          | Free tier                        |
| `basic`         | 60  | —           | —          | Standard (1 req/sec)             |
| `pro`           | 120 | —           | —          | Pro (2 req/sec)                  |
| `enterprise`    | 500 | —           | —          | High throughput (8 req/sec)      |
| `burst`         | 200 | —           | —          | Short burst limit                |
| `daily-10`      | —   | 10          | —          | Daily cap of 10 requests         |
| `daily-100`     | —   | 100         | —          | Daily cap of 100 requests        |
| `daily-1000`    | —   | 1000        | —          | Moderate batch processing        |
| `daily-5000`    | —   | 5000        | —          | Regular batch processing         |
| `hourly-60`     | 1   | —           | —          | Hourly cap of 60 requests        |
| `per-second-1`  | 60  | —           | 1          | Steady pace: 1 req/sec           |
| `per-second-5`  | 300 | —           | 5          | Intensive: 5 req/sec             |
| `internal-tool` | 300 | —           | —          | Internal tools (elevated limits) |

#### `remove <key-id>` — Revert to default policy rate limit

```bash
llm-router auth rate-limit remove <key-id> [--store memory]
```

---

## `llm-router anonymizer run` — Text Anonymization

```bash
llm-router anonymizer run --algorithm fast_masker [input_file] -o output_file \
  --disable-phone --disable-url --disable-ip --disable-pesel --disable-email
```

| Flag              | Default | Description                      |
|-------------------|---------|----------------------------------|
| `--algorithm`     | *(req)* | `fast_masker` or `pii`           |
| `[input_file]`    | stdin   | Input file (or STDIN if omitted) |
| `-o, --output`    | stdout  | Output file path                 |
| `--disable-phone` | `false` | Skip phone number anonymization  |
| `--disable-url`   | `false` | Skip URL anonymization           |
| `--disable-ip`    | `false` | Skip IP address anonymization    |
| `--disable-pesel` | `false` | Skip PESEL anonymization         |
| `--disable-email` | `false` | Skip email anonymization         |

---

## Seed File (Memory Store)

When `--store memory`, keys are persisted to a seed file:

```
~/.llm-router/configs/auth/memory-keys.json
```

After every `generate`, `delete`, `disable`, `enable`, or `rotate` operation the CLI automatically updates the seed
file. The router reads this file on startup and after each request, so changes are visible without restart.

### Seed File Format (ApiKeyRecord fields)

| Field             | Type          | Description                                                     |
|-------------------|---------------|-----------------------------------------------------------------|
| `key_id`          | `str`         | Unique identifier for this key                                  |
| `key_plain`       | `str`         | The plaintext API key                                           |
| `key_prefix`      | `str`         | First 7 characters of the plaintext (auto-generated if omitted) |
| `policy_name`     | `str`         | Default policy name                                             |
| `policy_override` | `dict`        | Inline override (e.g. `{"rate_limit": 300}`)                    |
| `is_active`       | `bool`        | Whether the key is currently valid                              |
| `expires_at`      | `float\|null` | Expiry timestamp                                                |
| `created_at`      | `float`       | Unix creation timestamp                                         |
| `last_used_at`    | `float\|null` | Last successful authentication time                             |
| `rotate_at`       | `float\|null` | Scheduled rotation time                                         |
| `grace_until`     | `float\|null` | Key remains valid until this time after rotation                |
| `metadata`        | `dict`        | Arbitrary metadata                                              |

---

## Key Format

All generated keys follow the `sk-litm-<base62>` format:

```
sk-litm-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789abcdefABCDEF123456789
```

| Property     | Value                                                      |
|--------------|------------------------------------------------------------|
| Prefix       | `sk-litm-` (configurable via `LLM_ROUTER_AUTH_KEY_PREFIX`) |
| Entropy      | 48 bytes cryptographically random (`secrets.token_bytes`)  |
| Charset      | base62 (`a-zA-Z0-9`)                                       |
| Total length | ≥55 chars (prefix + min 48 base62 characters)              |

---

## See Also

- **[Authentication docs](../llm_router_api/AUTHENTICATION.md)** — full auth architecture, seed files, deployment
  options
- **[Rate Limiting docs](../llm_router_api/RATE_LIMITING.md)** — sliding-window algorithm, monitoring, presets
