## Load Balancing Strategies

The `llm-router` supports various strategies for selecting the most suitable provider
when multiple options exist for a given model. This ensures efficient
and reliable routing of requests. The available strategies are:

### 1. `balanced` (Default)

* **Description:** This is the default strategy. It aims to distribute requests
  evenly across available providers by keeping track of how many times each provider has
  been used for a specific model. It selects the provider that has been used the least.
* **When to use:** Ideal for scenarios where all providers are considered equal
  in terms of capacity and performance. It provides a simple and effective way to balance the load.
* **Implementation:** Implemented in `llm_router_api.core.lb.balanced.LoadBalancedStrategy`.

### 2. `weighted`

* **Description:** This strategy allows you to assign static weights to providers.
  Providers with higher weights are more likely to be selected. The selection is deterministic,
  ensuring that over time, the request distribution closely matches the configured weights.
* **When to use:** Useful when you have providers with different capacities or performance
  characteristics, and you want to prioritize certain providers without needing dynamic adjustments.
* **Implementation:** Implemented in `llm_router_api.core.lb.weighted.WeightedStrategy`.

### 3. `dynamic_weighted` (beta)

* **Description:** An extension of the `weighted` strategy. It not only uses weights
  but also tracks the latency between successive selections of the same provider.
  This allows for more adaptive routing, as providers with consistently high latency
  might be de-prioritized over time. You can also dynamically update provider weights.
* **When to use:** Recommended for dynamic environments where provider performance
  can fluctuate. It offers more sophisticated load balancing by considering both
  configured weights and real-time performance metrics (latency).
* **Implementation:** Implemented in `llm_router_api.core.lb.weighted.DynamicWeightedStrategy`.

### 4. `first_available`

* **Description:** This strategy selects the very first provider that is available.
  It uses Redis to coordinate across multiple workers, ensuring that only one
  worker can use a specific provider at a time.
* **When to use:** Suitable for critical applications where you need the fastest
  possible response and want to ensure that a request is immediately handled by any available
  provider, without complex load distribution logic. It guarantees that a provider,
  once taken, is exclusive until released.
* **Implementation:** Implemented in `llm_router_api.core.lb.first_available.FirstAvailableStrategy`.

**When using the** `first_available` load balancing strategy, a **Redis server is required**
for coordinating provider availability across multiple workers.

### 4. `first_available_optim`
**UNDER DEVELOPMENT, DESCRIPTION WILL BE SOON**

The connection details for Redis can be configured using environment variables:

```shell
LLM_ROUTER_BALANCE_STRATEGY="first_available" \
LLM_ROUTER_REDIS_HOST="your.machine.redis.host" \
LLM_ROUTER_REDIS_PORT=redis_port \
```

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
   The Redis service should start automatically after installation.
   To ensure it's running and starts on system boot, you can use the following commands:

``` shell
sudo systemctl status redis-server
sudo systemctl enable redis-server
```

4. **Configure Redis (optional):**
   The default Redis configuration (`/etc/redis/redis.conf`) is usually sufficient
   to get started. If you need to adjust settings (e.g., address, port),
   edit this file. After making configuration changes, restart the Redis server:

```shell
sudo systemctl restart redis-server
```

---

## Extending with Custom Strategies

To use a different strategy (e.g., round‑robin, random weighted, latency‑based),
implement `ChooseProviderStrategyI` and pass the instance to `ProviderChooser`:

``` python
from llm_router_api.core.lb.chooser import ProviderChooser
from my_strategies import RoundRobinStrategy

chooser = ProviderChooser(strategy=RoundRobinStrategy())
```

The rest of the code – `ModelHandler`, endpoint implementations, etc. – will
automatically use the chooser you provide.