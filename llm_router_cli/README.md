# llm-router CLI — Command Reference

**Package:** `llm-router`
**Entry points:**

- `llm-router` — main CLI tool (auth, anonymizer, config, util, server, completion)

---

## Quick Start

```bash
pip install llm-router[api]
llm-router --help
llm-router --version
```

---

## Top-Level Commands

| Command          | Description                                                                       |
|------------------|-----------------------------------------------------------------------------------|
| `auth`           | Manage API keys, policies, and rate limiting                                      |
| `config`         | Auto-discover local providers & merge configs                                     |
| `anonymizer run` | Anonymize text using a selectable algorithm                                       |
| `util`           | Utility apps: `translate`, `genai-classifier`, `genai-data-augmentation`          |
| `server`         | Manage the REST API server (`start` / `stop` / `status` / `list`), many instances |
| `completion`     | Generate / install shell tab-completion (`bash` / `zsh`)                          |

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
llm-router util translate --llm-router-url URL --model M --dataset-path d.jsonl [--accept-field f] [-o out.jsonl]
llm-router util genai-classifier --dataset-dir DIR --prompts-dir P --output-dir O [--model-name M]
llm-router util genai-data-augmentation --dataset-path d.jsonl --prompt-file P --labels a,b [--output-dir DIR]
```

### `translate` — Translate texts in JSON/JSONL datasets

```bash
llm-router util translate \
  --llm-router-url http://localhost:8080 \
  --model speakleash/Bielik-11B-v2.3-Instruct \
  --dataset-path data.jsonl --dataset-path more.json \
  --accept-field text --accept-field title
```

| Flag                   | Default                 | Description                                                                              |
|------------------------|-------------------------|------------------------------------------------------------------------------------------|
| `--llm-router-url`     | `http://localhost:8080` | Base URL of the LLM router service                                      |
| `--model`              | *(req)*                 | Model name used for translation                                                          |
| `--dataset-path`       | *(req)*                 | Dataset file (JSON/JSONL); repeatable                                                    |
| `--dataset-type`       | *(auto)*                | Explicit `json` / `jsonl` (else inferred from extension)                                 |
| `--accept-field`       | *(all)*                 | Fields to translate; repeatable. Omit to translate **all string fields** in each record  |
| `--num-workers`        | `1`                     | Translation worker threads                                                               |
| `--batch-size`         | `8`                     | Texts per request                                                                        |
| `--llm-router-token`   | —                       | Auth token                                                                               |
| `--llm-router-timeout` | `10`                    | Per-request timeout (s)                                                                  |
| `--verbose`            | `false`                 | Enable verbose (DEBUG) logging of internal operations                                    |
| `-o, --output`         | —                       | Single output JSONL file (else `<stem>.translated.jsonl` per input)                      |

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

## `llm-router server` — REST API Server Lifecycle

Start / stop / reload the REST API server (a managed daemon with a PID file), inspect its status, or follow its log.
Unless your environment already sets them, `start` applies the same `LLM_ROUTER_*` defaults as
`run-rest-api-gunicorn.sh`.

| Sub-command          | Description                                                                                   |
| -------------------- | --------------------------------------------------------------------------------------------- |
| `start`              | Start in the background (daemon) or `--foreground` for debugging                              |
| `stop`               | SIGTERM the master **and its worker forks**, waits for the tree; `--force` SIGKILLs           |
| `reload`             | Restart the server: stop it, then start it again (`--graceful` = SIGHUP only)                 |
| `status`             | Show whether it is running, with a colored status card; `--all` for a fleet table             |
| `log`                | Follow the server log (tail -f style, colorized levels)                                       |
| `list`               | List every instance with status / PID / port (`--json` for scripting)                         |
| `rm-instance NAME`   | Delete a stopped instance's state directory                                                   |

Every sub-command takes `-i/--instance NAME`, so a host can run several routers at once — see
[Instances](#instances--running-several-servers-side-by-side).

`start` accepts the usual tuning flags (`--foreground`, `--host`, `--port`, `--server
{gunicorn,waitress,flask}`, `--models-config`, `--lb-strategy`, `--default-lang`, `--debug`, `--verbose`,
`--log-file`, `--pid-file`, `--auth`, `--redis-host`, `--redis-port`, `--redis-db`, `--redis-password`,
`--auth-redis-host`, `--auth-redis-port`, `--auth-redis-db`, `--auth-redis-password`), plus `--instance NAME` (which
instance to start), `--no-port-check` (skip the port pre-flight check), `--no-config-check` (skip the models-config
pre-flight check) and `--save-config` (remember the flags in the instance `config.env` — see [Saving a command
line](#saving-a-command-line---save-config)). The daemon log (`--log-file`)
follows `LLM_ROUTER_LOG_FILENAME` when the shell sets it — a bare file name resolves against the launch CWD — and falls
back to `~/.llm-router/server.log` only when the variable is unset. A **named** instance keeps its logs to itself: its
application log always lives in `~/.llm-router/instances/NAME/`, and the daemon console log sits next to it unless
`--log-file` says otherwise (see [Instances](#instances--running-several-servers-side-by-side)). Every `LLM_ROUTER_*`
variable in effect at launch — defaults + shell env + CLI overrides — is snapshotted into the run record
(`<pid-file>.run`) so `status` can show exactly how the server was started.

`--verbose` sets `LLM_ROUTER_VERBOSE=1` and makes the endpoints log the **raw, unmasked** request parameters, so the
log contains the PII that masking would normally strip. It is a troubleshooting switch only: when verbose mode is on,
the server prints a `WARNING` and waits 3 seconds before it starts serving, and it must never be enabled in
production. Leaving the flag out keeps the shipped default (`LLM_ROUTER_VERBOSE=0`).

### Reloading: `server reload`

`reload` **restarts** the instance: it stops the running server and starts it again, so everything the process holds
in memory is rebuilt — another models config, another port/host/engine, or changed code. A plain `SIGHUP` (what
`--graceful` still does) only makes Gunicorn recycle its workers; the master keeps whatever it loaded at startup,
which is why it is not enough after most configuration edits.

The stop half waits for the **whole process tree**, not just the process named in the PID file. Gunicorn's workers are
forks that inherit the master's listening socket, so a worker still running after the master exited keeps the port bound
and the start half would fail on `EADDRINUSE`. Every fork is therefore captured while the master still lives (after that
they are reparented to init and nothing links them back to the server), gets the SIGTERM itself, has the same 15 s to
drain, and is SIGKILLed when it ignores it — the same escalation the Gunicorn master applies once its own
`graceful_timeout` runs out. Once the master is down its forks get a further 5 s before they are force-killed, since the
master's grace was already their chance to drain. `stop` prints `Server stopped` and removes the PID file and run record
only when master and workers are all gone; a fork that somehow survives the SIGKILL makes it fail, naming the PIDs, and
leaves the state files in place so a retry (or `--force`) still knows what to clear. A process that has exited but has
not been reaped yet (a zombie, or a task the kernel is still deleting) counts as stopped: it released its side of the
socket the moment it exited, and waiting for somebody else's `wait()` would only stall the reload.

The start half restarts **the same instance** — `-i NAME` is replayed, so it reads that instance's `config.env` and
writes its PID file, log and metrics into the instance's own state tree. It also replays the environment the server was
really running with, taken from the run record. That matters for a launch configured through `LLM_ROUTER_*` variables
(the `run-rest-api-gunicorn.sh` wrapper does exactly that) rather than through `start` flags: flags alone would come back
with built-in defaults, e.g. port `8080` instead of the `8081` the instance was serving on.

```bash
llm-router server reload                # SIGTERM master + workers (15 s grace), then start again
llm-router server reload --force        # SIGKILL a server that ignores SIGTERM, then start again
llm-router server reload --graceful     # previous behavior: SIGHUP to the master, no restart
```

The start half replays the flags of the previous `start` from the run record (`<pid-file>.run`): `--host`, `--port`,
`--server`, `--models-config`, the Redis/auth flags, `--verbose`, plus the log file the server was writing to — so it
comes back exactly the way it went down. On top of those, `start` applies its usual precedence again
(`config.env > shell environment > recorded launch environment > built-in defaults`), so an edit to `config.env` — or a
variable exported in the shell running the reload — still wins over what the previous server ran with.
`reload` fails when no server is running (use `start`). It also aborts **before** stopping anything when the models
config recorded for the instance is missing or unparsable, so a typo never takes a working server down; if the stop
does not empty the process tree it aborts too (retry with `--force`), so `start` is never launched against a port a
leftover worker still holds, and if the start half fails the instance stays down while the message repeats the `start`
hint.

### Instances — running several servers side by side

Every `server` sub-command takes `-i/--instance NAME` (or `$LLM_ROUTER_INSTANCE`), so one host can run several
independent routers at the same time — one per project, per environment, or per provider pool. Each named instance
owns its own state tree, so nothing ever collides:

```text
~/.llm-router/
├── server.pid  server.pid.run  server.log          # the 'default' instance (historical layout)
└── instances/
    ├── dev/
    │   ├── config.env          per-instance LLM_ROUTER_* overrides
    │   ├── server.pid          PID of the daemon
    │   ├── server.pid.run      run record — how this instance was started
    │   ├── server.log          daemon's captured stdout/stderr
    │   ├── llm-router.log      the app's own rotating log (relative names land here)
    │   ├── metrics/prometheus/ private PROMETHEUS_MULTIPROC_DIR
    │   └── server.start.lock   lock guarding concurrent `start` calls
    └── prod/
        └── …
```

An instance name is a filesystem-safe slug: **1–64 characters** from `[A-Za-z0-9._-]`, starting with a letter or a
digit (no separators, no `..`). `default` is built in and reserved: its files stay directly in `~/.llm-router`, so
existing scripts, PID files and `run-rest-api-gunicorn.sh` keep working byte-for-byte unchanged.

#### Configuration per instance

The first `start` of a named instance writes a commented `config.env` template into its directory — an existing file
is never overwritten. Values are applied with this precedence:

```text
CLI flag  >  instance config.env  >  shell environment  >  built-in defaults
```

```bash
llm-router server start -i dev --port 8081     # state in ~/.llm-router/instances/dev
llm-router server start -i prod                # second router, port 8080
export LLM_ROUTER_INSTANCE=dev                 # pin a shell (or a systemd unit) to one instance
llm-router server status                       # now reports the 'dev' instance
llm-router server reload                       # … and reloads it
```

#### Saving a command line: `--save-config`

A `start` command line applies to that run only: after `server stop -i helpi`, the next plain `server start -i helpi`
reads `config.env`, the shell and the built-in defaults again, so `--port 8081 --lb-strategy balanced …` has to be
typed out once more. `--save-config` writes the flags **given on this command line** into the instance's `config.env`
before launching, which makes the settings survive a restart:

```bash
llm-router server start -i helpi --port 8081 --lb-strategy balanced \
    --models-config resources/configs/models-config-fake-names.json --save-config
Saved 3 setting(s) to /home/user/.llm-router/instances/helpi/config.env:
  LLM_ROUTER_MODELS_CONFIG
  LLM_ROUTER_BALANCE_STRATEGY
  LLM_ROUTER_SERVER_PORT

llm-router server stop -i helpi
llm-router server start -i helpi                 # same models config, port and strategy
```

```ini
# ~/.llm-router/instances/helpi/config.env — template entries are uncommented in place
LLM_ROUTER_SERVER_PORT=8081
# LLM_ROUTER_SERVER_HOST=127.0.0.1
LLM_ROUTER_MODELS_CONFIG=resources/configs/models-config-fake-names.json
# LLM_ROUTER_SERVER_WORKERS_COUNT=2
# LLM_ROUTER_LOG_LEVEL=DEBUG
LLM_ROUTER_BALANCE_STRATEGY=balanced
```

- Only explicitly-passed flags are stored — values taken from the shell or from the defaults are not, so saving never
  freezes a value the user did not choose. `--host`, `--port` and `--server` are saved too, and the resulting
  `config.env` is what a later `start` reads (precedence stays `CLI flag > config.env > shell > defaults`).
- An existing key is rewritten **in place** (a commented template line is uncommented), so hand-written comments,
  ordering and unrelated variables survive; repeating the identical command prints
  `… already up to date (3 setting(s))` instead of duplicating lines.
- Values are written **verbatim**, `--redis-password` and `--auth-redis-password` included — that is why the file is
  created/kept mode `0600`. The terminal only ever sees the *names* of the keys, never their values.
- `--save-config` with no option flags saves nothing and leaves the file untouched (it prints a hint). A value that
  cannot be represented in a shell file (an embedded newline) is skipped with a warning, and an unwritable
  `config.env` is a warning too — in both cases the server still starts.

#### Port pre-flight

Two instances on one host must not share a port, so `start` binds it **before** spawning and fails fast instead of
dying silently in the background:

```text
Error: port 8080 is already in use on 0.0.0.0 (instance 'prod').
Use --port/--host or set LLM_ROUTER_SERVER_PORT in /home/user/.llm-router/instances/prod/config.env.
```

Pass `--no-port-check` to skip the probe (a port held by a socket-activated service, or a check against a different
interface than the one the server binds). Concurrent `start` calls for the same instance are serialized by
`server.start.lock`; a lock older than 60 s (a killed `start`) is broken automatically.

The lock covers the gap between *"is it alive?"* and *"write the PID"* only. It is released as soon as the PID file is
published, so a `--foreground` server does not sit on it for its whole lifetime — otherwise `reload`, which starts the
moment the running server is gone, would read its own instance as "a start is already in progress". From then on the live
PID file is what keeps a second `start` out. A lock also carries the PID of the `start` that took it, and a command
leaving the scene removes it only if that PID is still its own, so a dying `start` cannot unlock a newer one.

#### Models-config pre-flight

`start` also checks the models config file it is about to hand to the server, so a typo in
`LLM_ROUTER_MODELS_CONFIG` fails on the terminal instead of leaving a daemon that dies a second later:

```text
Error: models config was not found: /srv/llm-router/resources/configs/models-config.json (instance 'prod').
Source: config.env /home/user/.llm-router/instances/prod/config.env.
Create the file, pass --models-config PATH, set LLM_ROUTER_MODELS_CONFIG in /home/user/.llm-router/instances/prod/config.env, or use --no-config-check to start anyway.
```

`Source:` names the layer the path came from — the `--models-config` flag, the instance `config.env`, the shell
environment or the built-in default — which is usually the whole fix. The check covers existence, readability,
valid JSON, a top-level JSON object and, mirroring the runtime loader, an `active_models` section whenever the
file defines at least one model. A file whose sections are all empty (`{"google_models": {}}`) stays legal: it
simply means "no models". Pass `--no-config-check` to skip the check.

A daemon publishes its PID *before* execing the server, so a startup failure the check cannot see (a schema the
loader rejects later, a provider key it cannot resolve) would still be swallowed. `start` therefore watches the
new daemon for 1.5 s: if it disappears, the PID and run-record files are removed and the console gets the daemon
log path plus the last 15 lines of that log — the traceback, in practice.

> **Note on Prometheus:** `prepare_prometheus_multiproc_dir()` wipes its directory on every start, so instances that
> shared `PROMETHEUS_MULTIPROC_DIR` would erase each other's counters. Every *named* instance therefore gets a private
> `PROMETHEUS_MULTIPROC_DIR` inside its own state directory (unless the variable is already set in the shell or
> `config.env`). The `default` instance keeps the historical shared directory.
>
> **Note on shared state:** the auth key store (`~/.llm-router/configs/auth/memory-keys.json`) is deliberately *not*
> per-instance — all instances on a host authenticate against the same keys.
>
> **Note on logs:** a *named* instance always keeps its **application** log inside its own state directory. Launch
> scripts typically export a bare `LLM_ROUTER_LOG_FILENAME` (`llm-router.log`), which the server resolves against its
> CWD — without anchoring, every instance started from one directory would append to the same file, where two rotating
> handlers truncate each other and lose entries. A relative value is therefore placed under
> `~/.llm-router/instances/NAME/` (`.`/`..` components are dropped so it cannot escape the instance tree); an absolute or
> `~`-relative path is honored as given. `start` additionally warns on stderr when a *running* instance already logs to
> the same file. The `default` instance keeps the historical launch-CWD behavior.

### `list` — every instance at a glance

```bash
llm-router server list
```

```text
NAME   STATUS     PID    PORT  SERVER    STARTED                   LOG
batch  ● stopped  -      8090  gunicorn  2026-09-16T19:58:29+0200  /home/user/.llm-router/instances/batch/llm-router.log
dev    ● running  51087  8081  gunicorn  2026-09-16T19:58:29+0200  /home/user/.llm-router/instances/dev/llm-router.log
prod   ● running  51088  8080  gunicorn  2026-09-16T19:58:29+0200  /home/user/.llm-router/instances/prod/llm-router.log
```

The **LOG** column is the **application's** own log — the file `server log` follows — taken from the run record, and
falls back to the daemon's console log only when no run record exists (an instance that never started). `--json`
reports both files separately as `app_log_file` and `log_file`.

An instance is listed when it has state (a PID / run record for `default`, any file for a named instance), so a
configured-but-never-started instance still shows up as `stopped`. `list` always exits `0`.

| Flag      | Default | Description                                                      |
|-----------|---------|------------------------------------------------------------------|
| `--json`  | `false` | Machine-readable array with `name`, `status`, `pid`, `port`, `server`, `started_at`, `pid_file`, `log_file`, `app_log_file`, `models_config` |
| `--color` | `auto`  | Colorize output — `auto` (TTY only) / `always` / `never`          |

### `stop --all` / `status --all` / `rm-instance`

```bash
llm-router server status --all        # one-line summary of every instance
llm-router server stop --all          # stop them all (newest first)
llm-router server stop -i dev         # stop a single instance
llm-router server rm-instance batch   # forget a stopped instance (deletes its state dir)
```

```text
$ llm-router server status --all
  Instances (3)

  batch  ● stopped  /home/user/.llm-router/instances/batch/server.pid
  dev    ● running  Server is running (pid 51087, gunicorn, port 8081)
  prod   ● running  Server is running (pid 51088, gunicorn, port 8080)
```

`status --all` exits `0` only when **every** instance is running; `stop --all` exits `1` when no instance exists at
all. `rm-instance` refuses to touch a running instance and the built-in `default`:

```text
Error: instance 'dev' is running (pid=51087). Stop it first: llm-router server stop -i dev
Error: default is the built-in instance and cannot be removed
```

> `--all` cannot be combined with `--instance` or `--pid-file`.

### `status` — colored status card

`status` renders a compact, color-coded card instead of a flat list (the
`Environment` section shown below is hidden by default — add `--show-env` to reveal it):

```text
  ✓ All good
  ●  Server is running (pid 7400, gunicorn, port 8080)

  Details
    PID            7400
    Log            /home/user/project/llm-router.log
    Started        2026-09-07T23:55:00+0200
    Server         gunicorn
    Host           0.0.0.0
    Port           8080
    Models config  /home/user/project/resources/configs/models-config.json
    Command        /usr/bin/python3 -m llm_router_api.rest_api

  Environment (5)
    LLM_ROUTER_BALANCE_STRATEGY  weighted
    LLM_ROUTER_REDIS_PASSWORD    ****
    LLM_ROUTER_SERVER_PORT       8080
```

The **Log** row shows the application's own rotating log (`LLM_ROUTER_LOG_FILENAME`, default `llm-router.log`) as an
**absolute** path: a named instance anchors a bare name to `~/.llm-router/instances/NAME/`, the `default` instance to
the CWD it was launched from (`<launch-dir>/llm-router.log`). In daemon mode the `default` instance also sends the
daemon's captured stdout/stderr to that **same** file, which is why a single log row is enough; a named instance keeps
them apart — its console capture goes to `~/.llm-router/instances/NAME/server.log`, and `server list --json` reports
both files as `app_log_file` and `log_file`. When the server is **not** running the header/dot turn red
(`✗ Not running`), and `status` exits with code `1`.

The **Models config** row behaves the same way as **Log**: when the server was started with a *relative* path (e.g.
`resources/configs/models-config.json`), the run record stores the **absolute** path anchored to the launch CWD, so
`status` shows the real location of the file.

Security: environment values whose key names a credential (`*PASSWORD*`,
`*SECRET*`, `*TOKEN*`, `*API_KEY*`, `*CREDENTIAL*`) are **masked** as `****`
so secrets are never echoed to the terminal.

| Flag         | Default                    | Description                                              |
|--------------|----------------------------|----------------------------------------------------------|
| `--color`    | `auto`                     | Colorize output — `auto` (TTY only) / `always` / `never` |
| `--show-env` | `false`                    | Show the `Environment` section (hidden by default)       |
| `--pid-file` | `~/.llm-router/server.pid` | PID file location                                        |

### `log` — follow the server log

`log` follows the **application's own log** by default — the file set by
`LLM_ROUTER_LOG_FILENAME` at start time: `app_log_file` from the run record when present, otherwise the variable itself,
anchored to the instance directory for a named instance and to the launch CWD for `default`. This works for both daemon
and `--foreground` servers, since the run record is written in both cases:

```bash
llm-router server log                              # app log: last 20 lines, then follow
llm-router server log --lines 200                  # more history
llm-router server log --no-follow                  # one-shot tail, then exit
llm-router server log --log-file ~/.llm-router/server.log   # daemon's console log (daemon mode only)
```

| Flag          | Default                    | Description                                                 |
|---------------|----------------------------|-------------------------------------------------------------|
| `--log-file`  | *(app log)*                | Explicit log file to follow (e.g. the daemon's console log) |
| `--lines`     | `20`                       | Initial lines to show (`0` for none)                        |
| `--no-follow` | `false`                    | Show the tail and exit (no `-f` style following)            |
| `--color`     | `auto`                     | Colorize output — `auto` (TTY only) / `always` / `never`    |
| `--pid-file`  | `~/.llm-router/server.pid` | PID file (run record) location for the app-log lookup       |

`stop`, `reload` and `status` additionally accept `--pid-file` (default
`~/.llm-router/server.pid`), and `stop`/`reload` accept `--force` to skip the SIGTERM grace period and send SIGKILL
(for `reload`, the server is still started again afterwards). Both wait for the master's worker forks as well as the
master itself, because a surviving fork keeps the listening socket bound. As
every other `server` sub-command, they all take `-i/--instance NAME` (see
[Instances](#instances--running-several-servers-side-by-side)); `stop` and `status` also take `--all`.

---

## `llm-router completion` — Shell Tab-Completion (bash / zsh)

Generates a tab-completion script from the live CLI tree — the very parser `llm-router --help` prints — so commands,
sub-commands at **every nesting level** (e.g. `auth key generate`,
`anonymizer run`, `config discover`), every option in **both spellings** — the long one (`--instance`) and the short
one (`-i`), long options listed first — and the top-level `--version` can never drift away from the real command line.
Options keep being offered **mid-command**, also after a value has been typed, so
`llm-router server start --port 8081 <TAB>` still completes `--models-config`, `-i` and the rest.

Arguments and option **values** complete as well:

| Value of                                                                                          | `<TAB>` offers                                                                 |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------|
| `--color`, `--store`, `--lb-strategy`, `--algorithm`, `--server`, `--dataset-type`, `--debug`, `--auth`, `--auth-redis-protocol` | the declared `choices` (`auto` / `always` / `never`, …)                          |
| `-i` / `--instance`, `server rm-instance <name>`                                                    | `default` plus the instances found under `~/.llm-router/instances`              |
| path options (`--log-file`, `--pid-file`, `--models-config`, `-o`, `--output-dir`, …) and the file arguments of `config merge <files>` / `anonymizer run [input]` | file names, directories with a trailing slash                |

Anything else that takes a value (`--host`, `--port`, `<key-id>`, `config discover <hosts> …`) is left alone rather
than completed with file names.

| Sub-command | Description                              |
|-------------|------------------------------------------|
| `bash`      | Print a bash completion script to stdout |
| `zsh`       | Print a zsh completion script to stdout  |

Manual installation:

```bash
eval "$(llm-router completion bash)"        # once per shell
# or permanently:
source <(llm-router completion zsh)
```

`--install` writes the script straight into the default rc file for the shell (`~/.bashrc` for bash, `~/.zshrc` for zsh;
created if missing):

```bash
llm-router completion bash --install
llm-router completion zsh --install
```

Re-running `--install` is idempotent: the script is wrapped in
`# >>> llm-router completion (<shell>) >>>` markers and any previous block is replaced in place, so no duplicates
accumulate in your rc file.

| Flag        | Default                  | Description                                       |
|-------------|--------------------------|---------------------------------------------------|
| `--install` | `false`                  | Append to the default rc file instead of printing |
| `--file`    | `~/.bashrc` / `~/.zshrc` | Target rc file for `--install`                    |

---

## Seed File (Memory Store)

When `--store memory`, keys are persisted to a seed file:

```
~/.llm-router/configs/auth/memory-keys.json
```

After every `generate`, `delete`, `disable`, `enable`, or `rotate` operation the CLI automatically updates the seed
file. The router reads this file on startup and after each request, so changes are visible without restart.

### Seed File Format (ApiKeyRecord fields)

| Field             | Type          | Description                                                                 |
|-------------------|---------------|-----------------------------------------------------------------------------|
| `key_id`          | `str`         | Unique identifier for this key                                              |
| `key_plain`       | `str`         | The plaintext API key                                                       |
| `key_prefix`      | `str`         | First 12 characters of the plaintext (shows the full `sk-llmr-live` prefix) |
| `policy_name`     | `str`         | Default policy name                                                         |
| `policy_override` | `dict`        | Inline override (e.g. `{"rate_limit": 300}`)                                |
| `is_active`       | `bool`        | Whether the key is currently valid                                          |
| `expires_at`      | `float\|null` | Expiry timestamp                                                            |
| `created_at`      | `float`       | Unix creation timestamp                                                     |
| `last_used_at`    | `float\|null` | Last successful authentication time                                         |
| `rotate_at`       | `float\|null` | Scheduled rotation time                                                     |
| `grace_until`     | `float\|null` | Key remains valid until this time after rotation                            |
| `metadata`        | `dict`        | Arbitrary metadata                                                          |

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
