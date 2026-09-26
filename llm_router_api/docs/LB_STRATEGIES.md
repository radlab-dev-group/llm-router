## Load Balancing Strategies

The `llm-router` supports various strategies for selecting the most suitable provider when multiple options exist for a
given model. This ensures efficient and reliable routing of requests. The available strategies are:

> **Model‑level `fallback_model` runs before the strategy.** A strategy is always asked to serve the model named by
> the client. Only when that model cannot be served at all — no providers, no healthy provider, or every provider busy
> until the selection timeout — `ModelHandler` reroutes the request to the configured `fallback_model` and the very
> same strategy then balances over the providers *of that model*. Strategies themselves are unaffected; the option is
> documented in [`MODELS_CONFIG.md`](MODELS_CONFIG.md).

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
| **5️⃣ Book‑keeping**                      | Keep the optimisation data up‑to‑date for future requests.                                     | After a provider is successfully acquired, the host is recorded as the *last host* (`:last_host`), added to the model‑specific host set (`:hosts`), and marked as occupied for this model in the Redis hash `host:<host>` (field `model`, refreshed on every selection and expiring after `LLM_ROUTER_LB_HOST_PIN_TTL_SECONDS`). |

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
[`first_available_optim`](#5-first_available_optim).  It keeps the host-reuse
flow and keep-alive bookkeeping, but replaces the binary
one-consumer lock per provider with **worker slots**: every
provider may serve up to `nworkers` concurrent requests at the same time
(optional provider field in `models-config.json`, default `1`).  Unlike
`first_available_optim`, a provider is considered busy only when **all** of its
slots are taken, and the load spreads over the **least loaded** provider rather
than sticking to the first one that still has capacity.

**Provider configuration**

| Field      | Type                      | Description                                                                                              | Default |
|------------|---------------------------|------------------------------------------------------------------------------------------------------------|---------|
| `nworkers` | `int` (or numeric string) | Maximum number of parallel requests allowed on this provider. Missing/invalid/non-positive values fall back to `1` with a warning logged. | `1`     |

**How it works**

| Step                                    | Purpose                                                                                         | Behaviour                                                                                                                                                                                                                                                                     |
|-----------------------------------------|-------------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **1️⃣ Least loaded with a free slot** | Load‑aware selection; the step that decides as long as any provider has capacity. | Active (healthy) providers whose host is free for the model are ranked by `(busy workers, last host, config order)` and acquired atomically – a lost race simply moves to the next candidate.  Busy workers are counted in absolute terms, and the config index comes from the `providers` argument, not from the health monitor (which reads a Redis set). |
| **2️⃣ Re‑use any known host**         | Safety net: prefer hosts that already have the model loaded. | As in `first_available_optim`; providers are skipped once their slot count reaches `nworkers`. |
| **3️⃣ Pick an unused host**           | Safety net: spread the load to a fresh host. | As in `first_available_optim`. |
| **4️⃣ Fallback to plain first‑available** | Guarantees a result even when nothing was acquired. | Delegates to the base `FirstAvailableStrategy`, which waits until a slot is released and raises `TimeoutError` after the configured `timeout` (default 60 s) if no slot frees up. |
| **5️⃣ Book‑keeping**                  | Keep the optimisation data up‑to‑date. | As in `first_available_optim`: `:last_host`, `:hosts` and host occupancy are updated after a successful acquisition. |

> **Fill order.** Because the ranking counts busy workers rather than
> `busy / nworkers`, providers fill in **layers** – one worker each, in
> configuration order, before any of them takes a second.  With
> `p1: nworkers=2`, `p2: nworkers=3`, `p3: nworkers=1` and no releases, six
> requests are served `p1‑s1, p2‑s1, p3‑s1, p1‑s2, p2‑s2, p2‑s3`.  A relative
> measure would answer with the largest provider on every tie and leave the
> small ones idle.

> **Why the load-aware step runs first, and why “re-use the last host” is not a
> step of its own.**  The two host-reuse steps split the provider list on
> “host already known” / “host not known yet”, so together they already consider
> **every** provider that has a free slot and always answer with the first one in
> configuration order; with the load-aware step behind them it could never decide
> anything.  “Re-use the last host” answers as soon as the previously used
> provider has *any* free slot, which with `nworkers` > 1 fills one provider to
> saturation before the next one is considered at all.  It therefore survives as
> a tie-breaker **inside one load level** of the ranking: a warm host keeps the
> request while traffic is light, and loses to an idle provider as soon as it is
> busier than one.

**Redis state**

* `<prefix>model:<model>:in_use:<provider>` – one **sorted set of live
  worker-slot leases per (model, provider)**; each member is the token of one
  held slot and its score is the moment that lease expires.  `ZCARD` is the
  provider's busy count.  A locally registered Lua script prunes expired
  leases and claims a slot only below the `nworkers` limit, so several router
  workers/instances share one capacity view.
* **A crashed router process heals itself.**  The process that holds a slot
  renews its leases from the KeepAliveMonitor thread.  If it dies (OOM kill,
  container restart) it stops renewing, the leases lapse and the provider's
  capacity comes back on its own — bounded by
  `LLM_ROUTER_LB_SLOT_LEASE_SECONDS` (default `120`).  Renewal is throttled to
  every third of the lease lifetime, so a one-second monitor tick does not turn
  into a Redis write per held slot per second.
* **A forgotten slot heals itself too.**  Expiry only covers a *dead* process;
  a request that never called `put_provider` (an abandoned streaming response
  whose generator was not closed) would keep a *live* process re-advertising
  the slot forever.  Renewal therefore stops after
  `LLM_ROUTER_LB_SLOT_MAX_AGE_SECONDS` (default `1800`) and the lease expires
  within one lease lifetime — a very long request may briefly share a slot
  rather than monopolise it.  `0` disables the cap.
* `<prefix>` is `fa_optim_nworkers_`.  Every model key of this strategy lives
  under it, so it does **not** share `model:<model>`, `:last_host` or `:hosts`
  with `first_available` / `first_available_optim` running against the same
  Redis database.  Host occupancy (`host:<host>` → `model`) is deliberately
  unprefixed: which model occupies a physical host is a property of the host,
  not of the strategy looking it up.
* **The host pin expires.**  `host:<host>` is refreshed on every selection and
  carries `LLM_ROUTER_LB_HOST_PIN_TTL_SECONDS` (default `3600`), so a host that
  stops serving its model — provider removed from the configuration, model
  retired — becomes available to another model again instead of staying
  reserved forever.  A host that keeps receiving traffic never loses the pin.
* The classic `:is_chosen` lock fields are **not** used by this strategy.
* Start-up cleanup (`clear_buffers=True`) removes this strategy's
  `:last_host` / `:hosts` keys **within its own prefix only**, and never
  touches `:in_use`.  Those leases belong to the other, still
  running worker processes; clearing them would over-admit exactly the
  requests those processes are serving.  (An earlier version also scanned a
  `:occupancy` suffix that no key ever carried.)
* Host occupancy semantics and the KeepAliveMonitor are otherwise unchanged –
  a host occupied by *another* model is still skipped.

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
`first_available_optim_nworkers` is a drop‑in replacement for
`first_available_optim`: with the default `nworkers=1` a provider still admits
exactly one request at a time.  It is not a bit‑for‑bit reimplementation of
the classic binary lock — it keeps its state under its own `fa_optim_nworkers_`
key prefix and in expiring leases instead of the `:is_chosen` fields, so a
router using it must not be mixed with one using `first_available_optim`
against the same model set (each would be blind to the other's occupancy).

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
