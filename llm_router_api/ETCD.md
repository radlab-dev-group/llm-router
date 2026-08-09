# Etcd-backed Configuration with Hot-Reload

## Overview

`llm-router` can store its `models-config` in **etcd** instead of a local JSON file. The config is loaded at startup and
continuously watched — when the value on the etcd key changes, all router instances reload the configuration
**on-the-fly** without any restart or re-deploy.

```
+-----------+         +--------+          /llm-router/models-config (JSON)
| Router 1  |────────>| etcd   |<───┐
| Router 2  |────────>|        |    │  watch_prefix
| Router N  |────────>|        |    │  (long-poll)
+-----------+         +--------+    │
                                    │ write (put / edit)
                                    ▼
                            etcdctl or API
```

## Why use etcd?

| Scenario                        | File-based config                | Etcd-backed config                  |
|---------------------------------|----------------------------------|-------------------------------------|
| Add/remove a provider           | Restart all containers           | Edit JSON in etcd → instant reload  |
| Multiple replicas see changes   | Each pod reads its own ConfigMap | All pods share the single key       |
| Canary / blue-green deployments | Manual orchestration             | Swap key value → roll out to group  |
| Rollback                        | Re-deploy old ConfigMap          | Write previous version back to etcd |

## Configuration

### Environment variables

All config-source settings are controlled by environment variables with the `LLM_ROUTER_` prefix.

| Variable                      | Default                                | Description                                                                                                  |
|-------------------------------|----------------------------------------|--------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_CONFIG_SOURCE`    | `"file"`                               | Backend: `"file"` (default) or `"etcd"`                                                                      |
| `LLM_ROUTER_ETCD_HOST`        | *(empty)*                              | etcd server hostname or IP. When using Helm with `etcd.enabled=true`, set to `<release-name>-etcd-headless`. |
| `LLM_ROUTER_ETCD_PORT`        | `2379`                                 | etcd TCP port.                                                                                               |
| `LLM_ROUTER_ETCD_CONFIG_KEY`  | `/llm-router/models-config`            | The etcd key that holds the models-config JSON.                                                              |
| `LLM_ROUTER_ETCD_TLS_ENABLED` | `false`                                | Enable TLS/mTLS for the etcd connection.                                                                     |
| `LLM_ROUTER_ETCD_CA_CERT`     | *(empty)*                              | Path to the CA certificate file (used when TLS is enabled).                                                  |
| `LLM_ROUTER_ETCD_CLIENT_CERT` | *(empty)*                              | Client certificate path for mTLS.                                                                            |
| `LLM_ROUTER_ETCD_CLIENT_KEY`  | *(empty)*                              | Client private key path for mTLS.                                                                            |
| `LLM_ROUTER_MODELS_CONFIG`    | `resources/configs/models-config.json` | Legacy: file path when `CONFIG_SOURCE=file`. Ignored when using etcd.                                        |

### Minimal etcd example (3 env vars)

```bash
export LLM_ROUTER_CONFIG_SOURCE=etcd
export LLM_ROUTER_ETCD_HOST=10.0.0.5       # your etcd cluster
export LLM_ROUTER_ETCD_PORT=2379
export LLM_ROUTER_ETCD_CONFIG_KEY=/llm-router/models-config
```

### TLS / mTLS

Set `LLM_ROUTER_ETCD_TLS_ENABLED=true` and provide the CA certificate (and optionally client cert + key):

```bash
export LLM_ROUTER_ETCD_TLS_ENABLED=true
export LLM_ROUTER_ETCD_CA_CERT=/etc/ssl/certs/etcd-ca.pem
# If your etcd requires mTLS:
export LLM_ROUTER_ETCD_CLIENT_CERT=/etc/ssl/certs/router-client.pem
export LLM_ROUTER_ETCD_CLIENT_KEY=/etc/ssl/private/router-client-key.pem
```

## Hot-Reload Mechanism

When `CONFIG_SOURCE=etcd`, the router starts a background **watcher thread** that uses etcd's `watch_prefix` long-poll
API (not polling). The lifecycle is:

1. **Startup** — connect to etcd, read the initial value, parse JSON → `ConfigState`.
2. **Watch** — open a blocking watch on the configured key prefix. When any value under that prefix changes, etcd
   returns an event.
3. **Parse & swap** — decode the new JSON, create an immutable `ConfigState` snapshot, and atomically swap the reference
   in every `ApiModelConfig` instance (router, strategies, model handlers).
4. **Log** — a log line at INFO level reports the number of active models after reload.

### What gets reloaded?

- Active models list
- Provider lists for each model (add / remove / reorder)
- Provider weights, api_host, api_token, keep_alive, tool_calling, etc.
- `active_models` mapping

**Nothing** requires a container restart — the new config is live within ~100 ms of the etcd write reaching all
watchers.

### Write-back (etcd only)

The etcd source supports writing back to etcd through the application API. Use this to dynamically add or remove
providers at runtime:

```python
from llm_router_api.core.model_config import ApiModelConfig

# Assuming you have an ApiModelConfig instance that was created with the etcd source:
api_config.put_model_provider(
    model_type="google_models",
    model_name="google/gemma-3-12b-it",
    provider={"id": "new-provider", "api_host": "...", "providers": [...]},
)
```

This writes the full config back to etcd and triggers the hot-reload callback for all instances.

## Installation (Helm)

### 1. Enable etcd in values.yaml

```yaml
etcd:
  enabled: true
  architecture: standalone

config:
  LLM_ROUTER_CONFIG_SOURCE: "etcd"
  # Uncomment to override defaults:
  # LLM_ROUTER_ETCD_HOST: "{{ .Release.Name }}-etcd-headless"
  # LLM_ROUTER_ETCD_PORT: "2379"
  # LLM_ROUTER_ETCD_CONFIG_KEY: "/llm-router/models-config"
```

### 2. Seed the initial config

```bash
kubectl exec -it $(kubectl get pods -l app.kubernetes.io/name=etcd -o name) \
  -- etcdctl put /llm-router/models-config \
  "$(cat resources/configs/models-config.json)"
```

Or via the Bitnami init job:

```bash
kubectl run etcdctl --rm -it --image bitnami/etcdctl:latest \
  --restart=Never -- \
  /opt/bitnami/scripts/etcdctl/etcdctl.sh put /llm-router/models-config "$(cat resources/configs/models-config.json)"
```

### 3. Deploy

The Helm chart includes an etcd subchart (`bitnamicharts/etcd` v10.x). The `deployment.yaml` template conditionally
mounts the models ConfigMap **only when `CONFIG_SOURCE=file`** and injects etcd environment variables **only when
`CONFIG_SOURCE=etcd`**.

```bash
helm upgrade --install llm-router ./helm_charts/llm-router \
  -f helm_charts/llm-router/values.yaml \
  --set config.LLM_ROUTER_CONFIG_SOURCE=etcd \
  --set etcd.enabled=true
```

## Migration from File to Etcd

### One-way: file → etcd

1. Deploy etcd (Helm chart or external cluster).
2. Upload the existing models-config JSON:
   ```bash
   etcdctl put /llm-router/models-config "$(cat resources/configs/models-config.json)"
   ```
3. Update Helm values or env vars to use `CONFIG_SOURCE=etcd`.
4. Redeploy — routers will now read from etcd and the ConfigMap volume is omitted.

### Rollback: etcd → file

1. Restore the models-config JSON back into the Kubernetes ConfigMap.
2. Set `LLM_ROUTER_CONFIG_SOURCE=file` in your Helm values / env vars.
3. Redeploy — routers will read from the mounted ConfigMap again.

## Architecture Summary

```
┌───────────────────────────────────────┐
│           FlaskEngine                 │
│  ┌─────────────────────────────────┐  │
│  │ ConfigSourceI (Interface)       │  │
│  │  ├─ FileConfigSource (file)     │  │
│  │  └─ EtcdConfigSource (etcd) ★   │  │
│  └──────────────┬──────────────────┘  │
│                 │ get_config_state()  │
│                 ▼                      │
│  ProviderStrategyFacade               │
│    ┌───────────────────────────────┐  │
│    │ LoadBalancedStrategy          │  │
│    │ WeightedStrategy              │  │
│    │ FirstAvailableStrategy        │  │
│    │ ...                           │  │
│    └──────────────┬────────────────┘  │
│                   │                    │
│                   ▼                    │
│           ApiModelConfig              │
│  (atomic state swap on config change) │
└───────────────────────────────────────┘
```

**Key types:**

| Class                    | Module            | Purpose                                                                                        |
|--------------------------|-------------------|------------------------------------------------------------------------------------------------|
| `ConfigState`            | `interface.py`    | Immutable snapshot (`active_models`, `models_configs`)                                         |
| `ConfigSourceI`          | `interface.py`    | Abstract interface (name, can_write, get_config_state, on_config_change, put_config, close)    |
| `FileConfigSource`       | `file_source.py`  | File-based source; no hot-reload                                                               |
| `EtcdConfigSource`       | `etcd_source.py`  | Etcd-backed source with watcher thread, auto-reconnect (exponential backoff 1→30s), write-back |
| `ApiModelConfig`         | `model_config.py` | Consumer — registers callback; swaps state atomically via `RLock`                              |
| `create_config_source()` | `__init__.py`     | Factory — dispatches to concrete source based on env var                                       |

## Troubleshooting

### Router fails to start with etcd

Check logs for:

```
[ConfigSource] Etcd connection attempt 1/5 failed: ...
[ConfigSource] Reconnect failed: ...
Could not connect to etcd at <host>:<port> after 5 attempts
```

Solutions:

- Verify the host/port are reachable from within the cluster.
- Ensure `LLM_ROUTER_ETCD_TLS_ENABLED` matches your etcd TLS configuration.
- Check certificate paths for mTLS.

### Config change not picked up

The watcher uses `watch_prefix`, so the key you write must match or be a child of the configured prefix:

```bash
# Correct — key matches CONFIG_KEY exactly:
etcdctl put /llm-router/models-config '<config-json>'

# Also correct — if you use a prefix like /llm-router/:
etcdctl put /llm-router/models-config '<config-json>'
```

### High CPU when many routers share the same etcd key

Each watcher opens an independent long-poll stream to etcd. This is normal and expected (the watch API itself is
efficient). If you have hundreds of routers, consider using a sidecar or a config pusher that broadcasts changes via a
separate channel instead of every pod watching directly.
