# llm-router CLI — Command Reference

**Package:** `llm-router`
**Entry points:**

- `llm-router` — main CLI tool (auth, anonymizer, config, util)

---

## Quick Start

```bash
pip install llm-router[api]
llm-router --help
llm-router --version
```

---

## Top-Level Commands

| Command          | Description                                                              |
|------------------|--------------------------------------------------------------------------|
| `auth`           | Manage API keys, policies, and rate limiting                             |
| `config`         | Auto-discover local providers & merge configs                            |
| `anonymizer run` | Anonymize text using a selectable algorithm                              |
| `util`           | Utility apps: `translate`, `genai-classifier`, `genai-data-augmentation` |

---

## `llm-router auth` — API Key & Authentication Management

### Command Tree

```
llm-router auth key <command>          # API key lifecycle
llm-router auth policy <command>       # Policy management
llm-router auth rate-limit <command>   # Per-key rate limit overrides
```

### Shared Flags (store-backed subcommands)

| Flag                    | Default   | Description                                           |
|-------------------------|-----------|-------------------------------------------------------|
| `--store <backend>`     | `memory`  | Key store: `memory`, `redis`, or `vault`              |
| `--auth-redis-host`     | *(empty)* | Auth Redis host                                       |
| `--auth-redis-port`     | `6379`    | Auth Redis port                                       |
| `--auth-redis-db`       | `0`       | Auth Redis database number                            |
| `--auth-redis-password` | —         | Auth Redis password                                   |
| `--auth-redis-protocol` | `2`       | Auth Redis protocol: `2` (RESP2) or `3` (RESP3)       |
| `--verbose`             | `false`   | Enable verbose (DEBUG) logging of internal operations |

> **Note:** These flags are shared by all **store-backed** subcommands —
> `key generate`, `key list`, `key delete`, `key disable`, `key enable`,
> `key rotate`, `policy create`, `rate-limit apply`, and `rate-limit remove`.
> They do **not** apply to the read-only `policy list` and `rate-limit list`
> subcommands.

> **Note:** Each `--auth-redis-*` flag falls back to a matching
> `LLM_ROUTER_AUTH_REDIS_<HOST|PORT|DB|PASSWORD|PROTOCOL>` environment
> variable before the built-in default is used. These auth-specific Redis
> flags are separate from the general `LLM_ROUTER_REDIS_*` env vars.

---

### Key Management: `llm-router auth key <command>`

#### `generate` — Create a new API key

```bash
llm-router auth key generate \
  --policy developer \
  --expires 1750000000 \
  --store memory
```

| Flag        | Default     | Description                                        |
|-------------|-------------|----------------------------------------------------|
| `--policy`  | `developer` | Policy name to assign                              |
| `--expires` | `None`      | Expiry (Unix timestamp or `None`)                  |
| `--output`  | *(stdout)*  | Output file path (created with `0600` permissions) |

Output: `sk-llmr-live-<base62>` key (plaintext shown **once** at creation) plus the generated `Key ID:` (e.g.
`key-fe8fc388`) — use the ID with `list`/`delete`/
`disable`/`enable`/`rotate`.

#### `list` — List all API keys

```bash
llm-router auth key list --store memory [--json]
```

| Flag     | Default | Description           |
|----------|---------|-----------------------|
| `--json` | `false` | Output in JSON format |

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

#### `create <name> [<json-policy>]` — Create a custom policy

```bash
# inline JSON
llm-router auth policy create my-team '{
  "can_access": true,
  "rate_limit": 120,
  "model_whitelist": ["gpt-4", "llama-3"]
}' --store memory

# from a file, or from stdin (-) — avoids leaking policy JSON into shell history
llm-router auth policy create my-team --file my-team.json
cat my-team.json | llm-router auth policy create my-team --file -
```

> **Persistence:** custom policies are saved to
> `$LLM_ROUTER_AUTH_CUSTOM_POLICIES_FILE` (default:
> `~/.llm-router/configs/auth/custom-policies.json`) and are resolved by the
> server in **new processes** — no restart required. `policy list` marks them
> with `(custom)`.

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

## `llm-router config` — Provider Discovery & Config Merging

### Command Tree

```
llm-router config discover <host...> [-o FILE] [--all-ports] [--no-active]  # Auto-discover providers
llm-router config merge <configs...> [-o FILE]                              # Merge multiple configs
```

### `discover` — Scan hosts for local LLM servers

```bash
llm-router config discover localhost -o models-config.json
llm-router config discover localhost 192.168.1.50 --all-ports
llm-router config discover "10.0.0.1:8080" "ollama.local:11434"
```

| Flag                       | Default      | Description                                           |
|----------------------------|--------------|-------------------------------------------------------|
| `<hosts>`                  | *(required)* | One or more hosts to scan (supports `host:port`)      |
| `-o, --output-config-file` | *(stdout)*   | Output path for generated config                      |
| `--all-ports`              | `false`      | Check all known ports even if first one is reachable  |
| `--no-active`              | `false`      | Skip writing the active_models section                |
| `--verbose`                | `false`      | Enable verbose (DEBUG) logging of internal operations |

> **Note on port scanning:** When you pass `host:port` (e.g. `"192.168.100.66:9090"`), the scanner checks that exact
> port first for each provider type (Ollama, vLLM, LM Studio, llama.cpp, KoboldCpp, TabbyAPI). If no models are found on
> the explicit port, it continues
> scanning the **default ports** for every discovered provider. To restrict scanning to only the explicit port (without
> fallback), use `--all-ports` in combination with specifying all known ports explicitly.

**Auto-discovered providers:**

| Provider  | Default Ports | Health Endpoint | Models Endpoint  |
|-----------|---------------|-----------------|------------------|
| Ollama    | 11434, 18765  | `/`             | `/api/tags`      |
| vLLM      | 8000, 7000    | `/health`       | `/v1/models`     |
| LM Studio | 1234, 1235    | `/`             | `/v1/models`     |
| llama.cpp | 8080          | `/health`       | `/v1/models`     |
| KoboldCpp | 5001          | `/`             | `/api/v1/models` |
| TabbyAPI  | 8080          | `/health`       | `/v1/models`     |

### `merge` — Merge multiple models-config.json files

```bash
llm-router config merge base.json override.json -o merged-config.json
```

Merges provider entries recursively (overlay wins on conflict), unions `active_models`, and deduplicates providers by
`api_host`.

| Flag                       | Default      | Description                                           |
|----------------------------|--------------|-------------------------------------------------------|
| `<configs>`                | *(required)* | Input config files to merge                           |
| `-o, --output-config-file` | *(stdout)*   | Output path for merged config                         |
| `--verbose`                | `false`      | Enable verbose (DEBUG) logging of internal operations |

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

## `llm-router util` — Utility Apps (translate / genai-classifier / genai-data-augmentation)

Light, dependency-free ports of the `llm-router-utils` applications. They read **local JSON/JSONL** files only (no
HuggingFace `datasets`, no `pandas` /
`openpyxl` / XLSX, no `tenacity`) and talk to the router through
`LLMRouterClient`.

### Command Tree

```
llm-router util translate --llm-router-host URL --model M --dataset-path d.jsonl [--accept-field f] [-o out.jsonl]
llm-router util genai-classifier --dataset-dir DIR --prompts-dir P --output-dir O [--model-name M]
llm-router util genai-data-augmentation --dataset-path d.jsonl --prompt-file P --labels a,b [--output-dir DIR]
```

### `translate` — Translate texts in JSON/JSONL datasets

```bash
llm-router util translate \
  --llm-router-host http://localhost:8080 \
  --model speakleash/Bielik-11B-v2.3-Instruct \
  --dataset-path data.jsonl --dataset-path more.json \
  --accept-field text --accept-field title
```

| Flag                   | Default  | Description                                                                             |
|------------------------|----------|-----------------------------------------------------------------------------------------|
| `--llm-router-host`    | *(req)*  | Base URL of the LLM router service                                                      |
| `--model`              | *(req)*  | Model name used for translation                                                         |
| `--dataset-path`       | *(req)*  | Dataset file (JSON/JSONL); repeatable                                                   |
| `--dataset-type`       | *(auto)* | Explicit `json` / `jsonl` (else inferred from extension)                                |
| `--accept-field`       | *(all)*  | Fields to translate; repeatable. Omit to translate **all string fields** in each record |
| `--num-workers`        | `1`      | Translation worker threads                                                              |
| `--batch-size`         | `8`      | Texts per request                                                                       |
| `--llm-router-token`   | —        | Auth token                                                                              |
| `--llm-router-timeout` | `10`     | Per-request timeout (s)                                                                 |
| `--verbose`            | `false`  | Enable verbose (DEBUG) logging of internal operations                                   |
| `-o, --output`         | —        | Single output JSONL file (else `<stem>.translated.jsonl` per input)                     |

> **Output:** without `-o`, each input `<stem>` writes `<stem>.translated.jsonl`
> next to it; with `-o`, all records go to that one file. **Input files are
> never overwritten.**
>
> **Default behavior:** without `--accept-field`, **all string-valued fields**
> of each record are sent for translation; non-string values and other record
> fields pass through unchanged.

### `genai-classifier` — Classify translated datasets (JSONL only)

```bash
llm-router util genai-classifier \
  --dataset-dir ./data --prompts-dir ./prompts --output-dir ./out \
  --model-name gpt-oss:120b --num-workers 2 --n-sample 50
```

| Flag                      | Default                 | Description                                 |
|---------------------------|-------------------------|---------------------------------------------|
| `--dataset-dir`           | *(req)*                 | Directory with the local `*.jsonl` datasets |
| `--dataset-path`          | —                       | Explicit dataset file(s); repeatable        |
| `--prompts-dir`           | *(req)*                 | Directory with `*.prompt` files             |
| `--output-dir`            | *(req)*                 | Where the result `.jsonl` files are stored  |
| `--model-name`            | `gpt-oss:120b`          | Model identifier passed to the router       |
| `--temperature`           | `0.0`                   | Sampling temperature                        |
| `--num-workers`           | `2`                     | Parallel worker threads                     |
| `--n-sample`              | `50`                    | Samples per field (`<=0` = all)             |
| `--batch-save-size`       | `5`                     | Records flushed to disk at once             |
| `--text-column-name`      | `Tekst`                 | Column holding the text to classify         |
| `--dry-run` / `--verbose` | `false`                 | Process without writing / DEBUG logging     |
| `--llm-router-url`        | `http://localhost:8080` | Base URL of the router                      |
| `--llm-router-token`      | —                       | Auth token                                  |
| `--llm-router-timeout`    | `10`                    | Per-request timeout (s)                     |

> Produces `<name>.jsonl` and `<name>_clean_labels.jsonl` (no XLSX).

### `genai-data-augmentation` — Augment a local JSONL dataset

```bash
llm-router util genai-data-augmentation \
  --dataset-path dataset.jsonl --prompt-file prompt.txt --labels cat,dog
```

| Flag                      | Default                 | Description                                      |
|---------------------------|-------------------------|--------------------------------------------------|
| `--dataset-path`          | *(req)*                 | Local JSONL dataset file                         |
| `--prompt-file`           | *(req)*                 | Prompt file                                      |
| `--labels`                | *(req)*                 | Comma-separated labels to augment                |
| `--n-samples`             | `5`                     | Samples per class to augment (`0` = all)         |
| `--n-examples`            | `3`                     | Augmented examples the LLM should generate       |
| `--samples-as-examples`   | `5`                     | Samples per class included in the prompt context |
| `--model-name`            | `gpt-oss:120b`          | Model identifier                                 |
| `--temperature`           | `0.7`                   | Sampling temperature                             |
| `--num-workers`           | `2`                     | Parallel worker threads                          |
| `--text-column-name`      | `Tekst`                 | Column holding the text                          |
| `--label-column-name`     | `label`                 | Column holding the label                         |
| `--output-dir`            | —                       | Override output directory (else dataset dir)     |
| `--batch-save-size`       | `5`                     | Records flushed to disk at once                  |
| `--dry-run` / `--verbose` | `false`                 | Process without writing / DEBUG logging          |
| `--llm-router-url`        | `http://localhost:8080` | Base URL of the router                           |
| `--llm-router-token`      | —                       | Auth token                                       |
| `--llm-router-timeout`    | `10`                    | Per-request timeout (s)                          |

> Produces `<stem>_augmented.jsonl` and `<stem>_augmented-train.jsonl` (no XLSX).

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

All generated keys follow the `sk-llmr-live-<base62>` format:

```
sk-llmr-live-aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789abcdefABCDEF123456789
```

| Property     | Value                                                           |
|--------------|-----------------------------------------------------------------|
| Prefix       | `sk-llmr-live-` (configurable via `LLM_ROUTER_AUTH_KEY_PREFIX`) |
| Entropy      | 48 bytes cryptographically random (`secrets.token_bytes`)       |
| Charset      | base62 (`a-zA-Z0-9`)                                            |
| Total length | ≥55 chars (prefix + min 48 base62 characters)                   |

---

## See Also

- **[Authentication docs](../llm_router_api/docs/AUTHENTICATION.md)** — full auth architecture, seed files, deployment
  options
- **[Rate Limiting docs](../llm_router_api/docs/RATE_LIMITING.md)** — sliding-window algorithm, monitoring, presets
