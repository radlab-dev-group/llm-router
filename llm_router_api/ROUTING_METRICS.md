# Router Prometheus Metrics

Additional Prometheus metrics for the LLM router core (routing, provider lifecycle, pipeline funnel).

Enabling these metrics requires `LLM_ROUTER_USE_PROMETHEUS=true` and the `metrics` extra (`pip install .[metrics]`).

## Overview

The router tracks **10 new metrics** across four categories:

| Category           | Metrics | Purpose                                                               |
|--------------------|---------|-----------------------------------------------------------------------|
| Routing & Provider | 4       | Visibility into provider selection, latency, errors, and LB strategy  |
| Pipeline Funnel    | 3       | Track how many requests pass through each pipeline stage              |
| Token Usage        | 1       | Track input/output token consumption per model                        |
| Streaming & Format | 2       | Track streaming vs non-streaming distribution and payload conversions |

---

## A. Routing & Provider Metrics

### `llm_router_provider_calls_total` *(Counter)*

Total number of successful calls to each provider type, grouped by model name.

**Labels:** `provider_type`, `model_name`

**Example output:**

```
llm_router_provider_calls_total{provider_type="openai", model_name="google/gemma-3-12b-it"} 42
llm_router_provider_calls_total{provider_type="ollama", model_name="google/gemma-3-12b-it"} 18
```

**Use case:** Track provider utilization distribution across models.

### `llm_router_provider_latency_seconds` *(Histogram)*

Latency of outbound calls to specific providers, independent of end-to-end client latency.

**Labels:** `provider_type`, `model_name`

**Buckets:** 10ms → 30s (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30)

**Example output:**

```
llm_router_provider_latency_seconds_count{provider_type="vllm", model_name="google/gemma-3-12b-it"} 100
llm_router_provider_latency_seconds_sum{provider_type="vllm", model_name="google/gemma-3-12b-it"} 45.2
```

**Use case:** Identify slow/degraded providers independently of client-side factors. Query example:

```promql
histogram_quantile(0.95, rate(llm_router_provider_latency_seconds_bucket[5m]))
```

### `llm_router_provider_error_total` *(Counter)*

Provider errors by type and HTTP error code (for retriable status codes) or classification (timeout, connection_error).

**Labels:** `provider_type`, `model_name`, `error_code`

**Example output:**

```
llm_router_provider_error_total{provider_type="ollama", model_name="gpt-oss:120b", error_code="429"} 5
llm_router_provider_error_total{provider_type="openai", model_name="google/gemma-3-12b-it", error_code="timeout"} 2
```

**Use case:** Alert on specific provider error spikes. Query example:

```promql
sum by (provider_type) (rate(llm_router_provider_error_total[5m]))
```

### `llm_router_lb_strategy_selected_total` *(Counter)*

Load balancing strategy selections per model, tracking which strategies are used for each model's providers.

**Labels:** `strategy`, `model_name`

**Example output:**

```
llm_router_lb_strategy_selected_total{strategy="balanced", model_name="google/gemma-3-12b-it"} 80
llm_router_lb_strategy_selected_total{strategy="weighted", model_name="openai/gpt-4"} 35
```

**Use case:** Verify load balancing strategy distribution. Useful when debugging or tuning LB strategies.

---

## B. Pipeline / Request Funnel Metrics

### `llm_router_pipeline_stage_total` *(Counter)*

Request counts at each pipeline stage with pass/fail result. Stages tracked:

| Stage               | Possible Results     |
|---------------------|----------------------|
| `provider_resolved` | `success`, `failure` |
| `request_received`  | `total` (always)     |
| `guardrail_request` | `pass`, `block`      |
| `masking`           | `applied`, `skipped` |

**Labels:** `stage`, `result`

**Example output:**

```
llm_router_pipeline_stage_total{stage="provider_resolved", result="success"} 1200
llm_router_pipeline_stage_total{stage="guardrail_request", result="block"} 45
```

**Use case:** Build a request funnel chart to see where requests drop off. Query example:

```promql
# Guardrail block rate
sum(rate(llm_router_pipeline_stage_total{stage="guardrail_request", result="block"}[5m])) / sum(rate(llm_router_pipeline_stage_total{stage="guardrail_request"}[5m]))
```

### `llm_router_retry_total` *(Counter)*

Retry attempts per model and HTTP error code that triggered the retry (429, 503, 504, 500).

**Labels:** `model_name`, `error_code`

**Example output:**

```
llm_router_retry_total{model_name="gpt-oss:120b", error_code="429"} 12
llm_router_retry_total{model_name="google/gemma-3-12b-it", error_code="503"} 3
```

**Use case:** Monitor provider reliability. High retry rates indicate infrastructure instability.

### `llm_router_retry_exhausted_total` *(Counter)*

Requests where all retry attempts were exhausted (final failure after retries).

**Labels:** `model_name`, `last_error_code`

**Example output:**

```
llm_router_retry_exhausted_total{model_name="gpt-oss:120b", last_error_code="503"} 8
```

**Use case:** Monitor unrecoverable provider failures for SLA tracking.

---

## C. Token Usage Metric

### `llm_router_tokens_total` *(Counter)*

Input/output token usage per model and provider, parsed from the LLM provider's response `usage` field.

**Labels:** `model_name`, `direction` (`input` / `output`), `provider_type`

**Example output:**

```
llm_router_tokens_total{model_name="google/gemma-3-12b-it", direction="input", provider_type="vllm"} 150000
llm_router_tokens_total{model_name="google/gemma-3-12b-it", direction="output", provider_type="vllm"} 45000
```

**Use case:** Cost tracking and throughput analysis. Query example:

```promql
# Total input tokens per model in last hour
sum by (model_name) (rate(llm_router_tokens_total{direction="input"}[1h]))

# Token cost estimation (approximate, adjust prices for your models)
rate(llm_router_tokens_total{direction="input", model_name="google/gemma-3-12b-it"}[1h]) * 0.00000015 + rate(llm_router_tokens_total{direction="output", model_name="google/gemma-3-12b-it"}[1h]) * 0.0000006
```

---

## D. Streaming & Response Format Metrics

### `llm_router_response_format_total` *(Counter)*

Distribution of streamed vs non-streamed responses per model and provider.

**Labels:** `format` (`streamed` / `non_streamed`), `model_name`, `provider_type`

**Example output:**

```
llm_router_response_format_total{format="streamed", model_name="google/gemma-3-12b-it", provider_type="ollama"} 95
llm_router_response_format_total{format="non_streamed", model_name="google/gemma-3-12b-it", provider_type="vllm"} 180
```

**Use case:** Monitor client streaming preferences and capacity planning for long-polling connections.

### `llm_router_payload_conversion_total` *(Counter)*

Number of payload conversions between provider types (e.g., when the endpoint format differs from the provider format).
Conversion paths include: `openai->ollama`, `ollama->openai`, `openai->anthropic`, `anthropic->openai`,
`openai->lmstudio`, `ollama->lmstudio`.

**Labels:** `from_type`, `to_type`

**Example output:**

```
llm_router_payload_conversion_total{from_type="openai", to_type="ollama"} 250
llm_router_payload_conversion_total{from_type="anthropic", to_type="openai"} 180
```

**Use case:** Track conversion overhead. Each conversion adds serialization/deserialization cost and potential for bugs.

---

## Grafana Dashboard Snippet

Here's a sample JSON panel config for the most important metrics:

```json
{
  "title": "Provider Calls (last hour)",
  "type": "graph",
  "targets": [
    {
      "expr": "sum by (provider_type) (rate(llm_router_provider_calls_total[1h]))",
      "legendFormat": "{{provider_type}}"
    }
  ]
}
```

Key PromQL queries for monitoring:

| Alert / Dashboard            | PromQL Query                                                                                                        |
|------------------------------|---------------------------------------------------------------------------------------------------------------------|
| Provider error rate per type | `sum by (provider_type) (rate(llm_router_provider_error_total[5m]))`                                                |
| Retry rate                   | `sum(rate(llm_router_retry_total[5m])) / sum(rate(llm_router_pipeline_stage_total{stage="provider_resolved"}[5m]))` |
| Average provider latency     | `rate(llm_router_provider_latency_seconds_sum[5m]) / rate(llm_router_provider_latency_seconds_count[5m])`           |
| Token usage per model        | `sum by (model_name) (rate(llm_router_tokens_total[1h]))`                                                           |

---

## Implementation Notes

- All metrics are **no-op when Prometheus is disabled** (`USE_PROMETHEUS=false`) — they silently skip recording.
- Metric recording failures are **caught and logged as debug-level** — they never break the request path.
- Uses `multiprocess.MultiProcessCollector` for Gunicorn multi-worker support (same pattern as existing metrics).
- Registered in `engine.py::__register_router_metrics_if_needed()` and stored on
  `flask_app.extensions["router_metrics"]`.
