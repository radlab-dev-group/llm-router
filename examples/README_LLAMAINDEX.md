## Using LlamaIndex with Local Models via the LLM‑Router

LlamaIndex’s `OpenAI` wrapper expects **OpenAI‑style model names** (e.g. `gpt-3.5-turbo`, `gpt-4`).  
When you want to run *local* models (Gemma, Ollama, vLLM, etc.) behind an LLM‑Router, the router must translate those
OpenAI names to the actual model identifiers used by the local providers.

### Why the mapping is required

* **LlamaIndex** validates the model name against a known list of OpenAI models to decide whether the call is a chat
  request, to obtain context‑window size, etc.
* If the wrapper receives a name it does not recognise (e.g. `google/gemma-3-12b-it`), it raises a `ValueError` like:

```
ValueError: Unknown model 'google/gemma-3-12b-it'. Please provide a valid OpenAI model name …
```

* By keeping the *OpenAI name* in the request and letting the router forward the request to the appropriate backend, you
  get the best of both worlds: LlamaIndex works unchanged, and the traffic is routed to your local model.

### Router configuration

The router’s configuration must contain a **section that lists OpenAI model names** (`openai_models`).  
Each entry defines one or more *providers* that actually serve the model.  
The key points are:

| Field            | Meaning                                                           |
|------------------|-------------------------------------------------------------------|
| **`id`**         | Arbitrary identifier for the provider instance.                   |
| **`api_host`**   | URL where the provider’s inference server is reachable.           |
| **`api_type`**   | The protocol the provider uses (`vllm`, `ollama`, …).             |
| **`model_path`** | **The *local* model identifier** (e.g. `google/gemma-3-12b-it`).  |
| **`weight`**     | Relative load‑balancing weight when several providers are listed. |

#### Example snippet

``` json
"openai_models": {
    (...)
    
    "gpt-3.5-turbo": {
        "providers": [
            {
                "id": "gpt_35_turbo-gemma3_12b-vllm-71:7000",
                "api_host": "http://192.168.100.71:7000/",
                "api_token": "",
                "api_type": "vllm",
                "input_size": 4096,
                "model_path": "google/gemma-3-12b-it",
                "weight": 1.0
            },
            {
                "id": "gpt_35_turbo-gemma3_12b-vllm-71:7001",
                "api_host": "http://192.168.100.71:7001/",
                "api_token": "",
                "api_type": "vllm",
                "input_size": 4096,
                "model_path": "google/gemma-3-12b-it",
                "weight": 1.0
            }
        ]
    },
    "gpt-4": {
        "providers": [
            {
                "id": "gpt-4-gpt-oss-20b-ollama-66:11434",
                "api_host": "http://192.168.100.66:11434",
                "api_token": "",
                "api_type": "ollama",
                "input_size": 256000,
                "model_path": "gpt-oss:120b"
                }
        ]
    }
},

...

"active_models": {
        "openai_models": [
        "gpt-3.5-turbo",
        "gpt-4"
        
        ...
    ]
}
```

### How it works end‑to‑end

1. **LlamaIndex code** creates an `OpenAI` client with a model name that the wrapper knows, e.g.:

```python
llm = OpenAI(model="gpt-3.5-turbo", api_base="http://localhost:8080", api_key="not-needed")
```

2. The request is sent to the **router** (`api_base`).
3. The router looks up `"gpt-3.5-turbo"` in `openai_models`, selects a provider, and forwards the request to the
   provider’s `api_host`.
4. The provider receives the request with `model_path="google/gemma-3-12b-it"` (or `"gpt-oss:120b"` for `gpt-4`) and
   runs the *local* model.
5. The response travels back through the router to LlamaIndex, which treats it exactly like an OpenAI response.

### Checklist for a working setup

- **Router is running** and reachable at the URL you pass to `api_base`.
- **`openai_models` section** contains all OpenAI names you intend to use from LlamaIndex.
- Each OpenAI name maps to at least one provider with the correct `model_path`.
- The **`active_models.openai_models`** list includes the names you want to expose (otherwise the router will ignore
  them).
- Local model servers (vLLM, Ollama, etc.) are up and listening on the `api_host` URLs specified.

### TL;DR

*Keep the model names you give to LlamaIndex identical to the OpenAI names defined in the router configuration. The
router will translate those names to the real local model identifiers (`model_path`). This mapping is the only thing
needed for LlamaIndex to work seamlessly with any self�