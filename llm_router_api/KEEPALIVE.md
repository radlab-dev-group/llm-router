# Keep‑Alive Utility Overview

The **keep‑alive** subsystem is responsible for periodically “pinging” model endpoints so that they stay warm and ready
to serve requests with minimal latency.  
It consists of two main components:

| Component              | Purpose                                                                                                                                                                                     | Key Methods                                                                                                                                        |
|------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| **`KeepAlive`**        | Sends a single HTTP request to a model provider. It resolves the correct provider configuration (API type, host, token, model name) and builds the request payload.                         | `send(model_name, host, prompt=None)` – performs the HTTP call.                                                                                    |
| **`KeepAliveMonitor`** | Schedules repeated keep‑alive calls for each `(model_name, host)` pair. It stores scheduling data in Redis, checks host availability, and triggers `KeepAlive.send` when a provider is due. | `record_usage(model_name, host, keep_alive)` – registers a provider for periodic pinging.<br>`start()` / `stop()` – control the background thread. |

## How It Works

1. **Provider discovery** – `KeepAlive._find_provider` looks up the provider configuration for a given model name and
   host inside the global `models_configs` dictionary.
2. **Endpoint resolution** – Depending on the provider’s `api_type` (`vllm`, `openai`, `ollama`), `_endpoint_for` builds
   the correct URL (`/v1/chat/completions` or `/api/chat`).
3. **HTTP request** – A JSON payload containing a short “keep‑alive” prompt (default: *“Send an empty message.”*) is
   posted to the endpoint.
4. **Scheduling** – `KeepAliveMonitor` stores metadata in Redis:
    * A hash key (`keepalive:provider:<model>:<host>`) with `keep_alive_seconds`.
    * A sorted‑set (`keepalive:providers:next_wakeup`) that orders providers by the next scheduled wake‑up timestamp.
5. **Background loop** – The monitor thread wakes up every `check_interval` seconds, fetches due providers, verifies
   that the host is free (via the optional `is_host_free_callback`), and invokes `KeepAlive.send`. After a successful
   ping, the next wake‑up time is recomputed.

## Integration Points

- **Strategy implementations** (e.g., `FirstAvailableOptimStrategy`) create a `KeepAlive` instance and pass it to a
  `KeepAliveMonitor`.
- When a provider is selected, the strategy calls `keep_alive_monitor.record_usage(model_name, host, keep_alive)` so the
  monitor knows to ping that endpoint.
- The monitor runs automatically in the background once `start()` is called (typically during strategy initialization).

## Configuring Keep‑Alive

Provider configurations live in the global `models_configs` JSON (see `resources/configs/models-config*.json`).  
To enable keep‑alive for a specific provider, add a `keep_alive` field with a duration string:

```json
{
  "model_name": "gpt‑4",
  "providers": [
    {
      "api_type": "openai",
      "api_host": "http://localhost:8000",
      "api_token": "YOUR_TOKEN",
      "keep_alive": "2m"
      // ping every 2 minutes
    }
  ]
}
```

Supported duration units:

| Unit    | Suffix | Meaning       |
|---------|--------|---------------|
| seconds | `s`    | e.g., `"30s"` |
| minutes | `m`    | e.g., `"5m"`  |
| hours   | `h`    | e.g., `"1h"`  |

If the `keep_alive` field is omitted or falsy, the provider will **not** be scheduled for periodic pings.

## Example Usage

```python
from llm_router_api.core.keep_alive import KeepAlive
from llm_router_api.core.monitor.keep_alive_monitor import KeepAliveMonitor

# Assume `models_configs` has been loaded from the JSON config files.
keep_alive = KeepAlive(models_configs=models_configs)

monitor = KeepAliveMonitor(
    redis_client=redis_client,
    keep_alive=keep_alive,
    check_interval=10.0,  # check every 10 seconds
    is_host_free_callback=my_is_host_free,
    clear_buffers=True,  # clean old keys on start
)

monitor.start()

# When a provider is selected somewhere in the routing logic:
monitor.record_usage(
    model_name="gpt‑4",
    host="http://localhost:8000",
    keep_alive="2m"
)
```

The monitor will now ping the `gpt‑4` endpoint every two minutes, provided the host is not busy with another model.

## Logging

Both `KeepAlive` and `KeepAliveMonitor` emit detailed logs at the `DEBUG` and `INFO` levels, prefixed with
`[keep-alive]`. Adjust your logger configuration to capture these messages for troubleshooting.

---

*Keep‑alive helps maintain low‑latency responses by preventing model containers from idling out. Proper configuration
and integration with your routing strategy ensure a smooth, responsive LLM service.*