## Load Balancing Strategies

The `llm-router` supports various strategies for selecting the most suitable provider when multiple options exist for a
given model. This ensures efficient and reliable routing of requests. The available strategies are:

---

### 1. `balanced` (Default)

* **Description:** This is the default strategy. It aims to distribute requests evenly across available providers by
  keeping track of how many times each provider has been used for a specific model. It selects the provider that has
  been used the least.
* **When to use:** Ideal for scenarios where all providers are considered equal in terms of capacity and performance. It
  provides a simple and effective way to balance the load.
* **Implementation:** Implemented in `llm_router_api.core.lb.balanced.LoadBalancedStrategy`.

---

### 2. `weighted`

* **Description:** This strategy allows you to assign static weights to providers. Providers with higher weights are
  more likely to be selected. The selection is deterministic, ensuring that over time, the request distribution closely
  matches the configured weights.
* **When to use:** Useful when you have providers with different capacities or performance characteristics, and you want
  to prioritize certain providers without needing dynamic adjustments.
* **Implementation:** Implemented in `llm_router_api.core.lb.weighted.WeightedStrategy`.

---

### 3. `dynamic_weighted` (beta)

* **Description:** An extension of the `weighted` strategy. It not only uses weights but also tracks the latency between
  successive selections of the same provider. This allows for more adaptive routing, as providers with consistently high
  latency might be de-prioritized over time. You can also dynamically update provider weights.
* **When to use:** Recommended for dynamic environments where provider performance can fluctuate. It offers more
  sophisticated load balancing by considering both configured weights and real-time performance metrics (latency).
* **Implementation:** Implemented in `llm_router_api.core.lb.weighted.DynamicWeightedStrategy`.

---

### 4. `first_available`

* **Description:** This strategy selects the very first provider that is available. It uses Redis to coordinate across
  multiple workers, ensuring that only one worker can use a specific provider at a time.
* **When to use:** Suitable for critical applications where you need the fastest possible response and want to ensure
  that a request is immediately handled by any available provider, without complex load distribution logic. It
  guarantees that a provider, once taken, is exclusive until released.
* **Implementation:** Implemented in `llm_router_api.core.lb.first_available.FirstAvailableStrategy`.

**When using the** `first_available` load balancing strategy, a **Redis server is required**
for coordinating provider availability across multiple workers.

---

### 5. `first_available_optim`

**What it is**  
`first_available_optim` is an enhanced version of the plain *first‑available* load‑balancing strategy. It uses Redis to
coordinate across multiple workers and tries to reuse a host that has already been used for the requested model before
falling back to the classic “pick the first free provider” logic.

**How it works**

| Step                                    | Purpose                                                                                        | Behaviour                                                                                                                                                                                                |
|-----------------------------------------|------------------------------------------------------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **1️⃣ Re‑use the last host**              | If the model was previously run on a specific host and that host is currently free, select it. | The host identifier is stored in a Redis key `:last_host`. The strategy checks that the host is not occupied by another model and attempts an atomic acquisition of a provider on that host.             |
| **2️⃣ Re‑use any known host**             | Prefer any host that already has the model loaded.                                             | A Redis set `:hosts` tracks all hosts where the model is currently loaded. The strategy scans the provider list, picks a free provider on one of those hosts, and locks it atomically.                   |
| **3️⃣ Pick an unused host**               | Spread the load to a fresh host when no suitable “known” host is available.                    | It looks for a provider whose host is **not** present in the `:hosts` set and is not occupied, then acquires it.                                                                                         |
| **4️⃣ Fallback to plain first‑available** | Guarantees a result even if the optimisation steps fail.                                       | If none of the previous steps succeed, the strategy delegates to the base `FirstAvailableStrategy`, which simply selects the first free provider.                                                        |
| **5️⃣ Book‑keeping**                      | Keep the optimisation data up‑to‑date for future requests.                                     | After a provider is successfully acquired, the host is recorded as the *last host* (`:last_host`), added to the model‑specific host set (`:hosts`), and marked as occupied in a Redis hash `:occupancy`. |

**When to use it**

* **Low‑latency / high‑throughput workloads** – Re‑using the same host avoids the overhead of re‑loading a large model,
  resulting in faster responses.
* **Environments with a limited number of hosts** – The strategy maximises the utilization of already‑occupied hosts
  while still allowing the load to be spread when needed.
* **Multi‑worker deployments** – Because all state is stored in Redis, many processes (or even different machines) can
  safely share the optimisation logic without race conditions.

**Summary**  
`first_available_optim` combines the simplicity of the *first‑available* approach with smart host reuse, reducing
model‑loading latency and improving overall throughput while still providing a reliable fallback mechanism. All
coordination is performed via Redis, ensuring safe concurrent operation across multiple workers.

---

### 6. `first_available_optim_nworkers`

**What it is**  
`first_available_optim_nworkers` is a permissive extension of
[`first_available_optim`](#5-first_available_optim).  It keeps the same host-reuse
flow (steps 1-3) and keep-alive bookkeeping, but replaces the binary
one-consumer lock per provider with a **worker-slot counter**: every
provider may serve up to `nworkers` concurrent requests at the same time
(optional provider field in `models-config.json`, default `1`).

**Provider configuration**

| Field      | Type                      | Description                                                                                              | Default |
|------------|---------------------------|------------------------------------------------------------------------------------------------------------|---------|
| `nworkers` | `int` (or numeric string) | Maximum number of parallel requests allowed on this provider. Missing/invalid/non-positive values fall back to `1` with a warning logged. | `1`     |

**How it works**

| Step                                    | Purpose                                                                                         | Behaviour                                                                                                                                                                                                                                                                     |
|-----------------------------------------|-------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **1️⃣ Re‑use the last host**              | Reuse the host of the previous selection when it still has a free slot.                         | Same as `first_available_optim`, but the acquisition now claims one worker slot instead of a binary lock.                                                                                                                                                                       |
| **2️⃣ Re‑use any known host**             | Prefer hosts that already have the model loaded.                                                 | Same as above – providers on known hosts are skipped once their slot counter reaches `nworkers`.                                                                                                                                      |
| **3️⃣ Pick an unused host**               | Spread the load to a fresh host when no “known” host has capacity.                               | Same as above.                                                                                                                                                                                                                                                                |
| **4️⃣ Least loaded with a free slot**     | Load‑aware selection before giving up.                                                          | A single `HGETALL` snapshot of the `model:<model>:in_use` hash is taken; active (healthy) providers whose host is free for the model are ranked by `(busy, busy / nworkers, config order)` and acquired atomically – a lost race simply moves to the next candidate. |
| **5️⃣ Fallback to plain first‑available** | Guarantees a result even when nothing was acquired.                                             | Delegates to the base `FirstAvailableStrategy`, which waits until a slot is released and raises `TimeoutError` after the configured `timeout` (default 60 s) if no slot frees up.                                                                                             |
| **6️⃣ Book‑keeping**                      | Keep the optimisation data up‑to‑date.                                                          | As in `first_available_optim`: `:last_host`, `:hosts` and `:occupancy` are updated after a successful acquisition.                                                                                                                                                             |

**Redis state**

* `model:<model>:in_use` – hash with one field per provider; the value is the
  number of busy workers (missing field = 0).  Counters are managed by two
  locally registered Lua scripts (atomic acquire: increment only below the
  limit; atomic release: decrement and delete the field at zero), so multiple
  router workers/instances share one capacity view.
* The classic `:is_chosen` lock fields are **not** used by this strategy.
* With `clear_buffers=True` (the default) all `*:in_use` keys are removed on
  router start, the same way the classic locks are cleared.
* Host occupancy semantics (`host:<host>` → `model`) and the KeepAliveMonitor
  are unchanged – a host occupied by *another* model is still skipped.

**Example**

```json
{
  "google_models": {
    "google/gemma-3-12b-it": {
      "providers": [
        {
          "id": "gemma3_12b-vllm-71:7000",
          "api_host": "http://192.168.100.71:7000/",
          "api_type": "vllm",
          "nworkers": 4
        },
        {
          "id": "qwen3-coder-ollama",
          "api_host": "http://192.168.100.66:11434",
          "api_type": "ollama",
          "nworkers": 1
        }
      ]
    }
  }
}
```

**When to use it**

* **Backends that support parallel requests** – vLLM / llama.cpp servers with
  several concurrent slots; set `nworkers` to the real parallelism of the
  engine so the router never overloads it.
* **Higher throughput on a limited host pool** – the same host can absorb
  several simultaneous requests instead of one.
* Everything from `first_available_optim` still applies (Redis required,
  multi‑worker safe, reliable timeout fallback).

**Summary**  
`first_available_optim_nworkers` is drop‑in compatible with
`first_available_optim` (`nworkers` defaults to `1`, which reproduces the
classic binary lock one‑to‑one) and adds per‑provider concurrency with a
least‑loaded selection step, shared atomically through Redis.

---

### 7. `AdaptiveStrategy` (beta)

* **Description:** An experimental strategy that extends `DynamicWeightedStrategy` with online learning. It dynamically
  adjusts weights to minimize the intervals between consecutive provider selections, with strong penalties for failures
  (interval < 0.5s) and performance degradation. Maps predicted cost to selection weights using softmax with temperature
  and minimum probability parameters.
* **When to use:** Experimental — suitable for testing in non-critical environments where adaptive load balancing is
  desired but `DynamicWeightedStrategy` does not provide the right tuning characteristics.
* **Implementation:** Implemented in `llm_router_api.core.lb.strategies.beta.adaptive.AdaptiveStrategy`.

---

## Environments and Redis installation

The connection details for Redis can be configured using environment variables:

| Environment variable          | Default    | Description                                                                                                        |
|-------------------------------|------------|--------------------------------------------------------------------------------------------------------------------|
| `LLM_ROUTER_BALANCE_STRATEGY` | `balanced` | Load‑balancing strategy name (e.g., balanced, weighted, dynamic_weighted, first_available, first_available_optim, first_available_optim_nworkers). |
| `LLM_ROUTER_REDIS_HOST`       | –          | Hostname of the Redis server (mandatory).                                                                          |
| `LLM_ROUTER_REDIS_PORT`       | –          | Port of the Redis server (mandatory).                                                                              |
| `LLM_ROUTER_REDIS_DB`         | `0`        | Optional Redis database index.                                                                                     |
| `LLM_ROUTER_REDIS_TIMEOUT`    | `60`       | Connection timeout in seconds.                                                                                     |

---

**Installing Redis on Ubuntu**

To install Redis on an Ubuntu system, follow these steps:

1. **Update package list:**

```shell
sudo apt update
```

2. **Install Redis server:**

```shell
sudo apt install redis-server
```

3. **Start and enable Redis service:**
   The Redis service should start automatically after installation. To ensure it's running and starts on system boot,
   you can use the following commands:

``` shell
sudo systemctl status redis-server
sudo systemctl enable redis-server
```

4. **Configure Redis (optional):**
   The default Redis configuration (`/etc/redis/redis.conf`) is usually sufficient to get started. If you need to adjust
   settings (e.g., address, port), edit this file. After making configuration changes, restart the Redis server:

```shell
sudo systemctl restart redis-server
```

---

## Extending with Custom Strategies

To use a different strategy (e.g., round‑robin, random weighted, latency‑based), implement `ChooseProviderStrategyI` and
pass the instance to `ProviderChooser`:

``` python
from llm_router_api.core.lb.chooser import ProviderChooser
from my_strategies import RoundRobinStrategy

chooser = ProviderChooser(strategy=RoundRobinStrategy())
```

The rest of the code – `ModelHandler`, endpoint implementations, etc. – will automatically use the chooser you provide.