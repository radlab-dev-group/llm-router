# Models configuration description (JSON)

## 📄 Purpose

This document explains the **model configuration** used by the LLM Router.  
It describes the JSON schema that drives **`ModelHandler`** and **`ApiModelConfig`**, clarifies each field, and provides
a ready‑to‑use example (`models-config.json`).  
Having a single source of truth for model definitions makes it easy to:

* Add or remove providers for a given model.
* Switch between cloud (OpenAI, Google) and local (vLLM, Ollama) back‑ends.
* Control load‑balancing, keep‑alive, and tool‑calling options per provider.
* Activate only the models you want to expose through the router.

---  

## 🏗️ High‑level structure

```plain text
{
  "<model_type>": {               # e.g. "google_models", "openai_models", "qwen_models"
    "<model_name>": {            # full identifier used by the router, e.g. "google/gemma-3-12b-it"
      "providers": [ … ],        # primary providers (used for normal traffic)
      "providers_sleep": [ … ]   # optional low‑priority providers (used when others are busy)
    },
    …
  },
  "active_models": {              # **required** – tells the router which models are enabled
    "<model_type>": [ "<model_name>", … ],
    …
  }
}
```

* **Model type** – a top‑level key grouping models that share the same provider‑type logic.
* **Model name** – the identifier that appears in API calls (`model` field).
* **`providers`** – a list of dictionaries, each describing a concrete endpoint.
* **`providers_sleep`** (optional) – “sleeping” providers that are only used when all primary providers are unavailable
  or overloaded.
* **`active_models`** – the only place where a model is marked as *active*. If a model is missing here, the router will
  ignore it even if it is present in the rest of the file.

---  

## 🔎 Detailed field description

### Provider dictionary (items in `providers` / `providers_sleep`)

| Field          | Type                      | Description                                                                                                                         | Example                         |
|----------------|---------------------------|-------------------------------------------------------------------------------------------------------------------------------------|---------------------------------|
| `id`           | `str`                     | Unique identifier for the provider instance (used for logging & selection).                                                         | `"gemma3_12b-vllm-71:7000"`     |
| `api_host`     | `str`                     | Base URL of the provider API (must include protocol, may contain trailing slash).                                                   | `"http://192.168.100.71:7000/"` |
| `api_token`    | `str`                     | Authentication token; empty string if not required.                                                                                 | `""`                            |
| `api_type`     | `str`                     | Type of the backend – determines which concrete `BaseProvider` class is used (`openai`, `vllm`, `ollama`, …).                       | `"vllm"`                        |
| `input_size`   | `int` (or numeric string) | Maximum context length the provider accepts. The `ApiModel.from_config` helper converts it to `int`.                                | `4096`                          |
| `model_path`   | `str`                     | Path or name of the model on the provider side (used by Ollama, vLLM, etc.). May be empty for providers that infer it from the URL. | `"gpt-3.5-turbo-0125"`          |
| `weight`       | `float`                   | Relative weight for **weighted‑random** load‑balancing strategies. Default `1.0`.                                                   | `0.1`                           |
| `keep_alive`   | `str`                     | Optional keep‑alive duration (e.g. `"35m"`). Empty or `null` means the provider is not kept alive.                                  | `"35m"`                         |
| `tool_calling` | `bool`                    | Whether the provider supports tool‑calling (function calling).                                                                      | `true`                          |

### `active_models` section

```json
{
  (...)
  "active_models": {
    "google_models": [
      "google/gemma-3-12b-it",
      "google/gemini-2.5-flash-lite"
    ],
    "openai_models": [
      "openai/gpt-3.5-turbo-0125",
      "gpt-oss:20b",
      "gpt-oss:120b"
    ],
    "qwen_models": [
      "qwen3-coder:30b"
    ]
  }
}
```

* The **key** must match a top‑level model type defined elsewhere in the file.
* The **list** contains the exact model names that appear under that type.
* Only the models listed here are loaded by `ApiModelConfig._read_active_models()` and later exposed by `ModelHandler`.

---  

## 🧩 How `ModelHandler` uses the config

1. **Construction**

```python
handler = ModelHandler(
    models_config_path="/path/to/models-config.json",
    provider_chooser=my_provider_strategy
)
```

* `ApiModelConfig` reads the file, extracts `active_models`, and builds `models_configs` – a dict that maps each active
  model name to its full configuration (including the `providers` list).

2. **Fetching a provider**

```python
api_model = handler.get_model_provider("google/gemma-3-12b-it")
```

* `handler.api_model_config.models_configs[model_name]` returns the raw dict for the model.
* The `ProviderStrategyFacade` selects a concrete provider dict (based on the chosen load‑balancing algorithm).
* `ApiModel.from_config()` turns that dict into an `ApiModel` instance – a lightweight object that stores fields like
  `api_host`, `api_type`, `keep_alive`, etc.

3. **Listing active models**

```python
active = handler.list_active_models()
```

* Returns a dict grouped by model type, each entry containing a short, sanitized view of the primary provider (removing
  secret fields such as `api_token` and `model_path`).

---  

## 📦 Sample configuration (`models-config.json`)

Below is a trimmed version of the real file located in `resources/configs/models-config.json`.  
Copy it to your own configuration directory and adjust the values to match your environment.

```json
{
  "google_models": {
    "google/gemma-3-12b-it": {
      "providers": [
        {
          "id": "gemma3_12b-vllm-71:7000",
          "api_host": "http://192.168.100.71:7000/",
          "api_token": "",
          "api_type": "vllm",
          "input_size": 4096,
          "model_path": "",
          "weight": 1.0,
          "keep_alive": null,
          "tool_calling": false
        },
        {
          "id": "gemma3_12b-vllm-71:7001",
          "api_host": "http://192.168.100.71:7001/",
          "api_token": "",
          "api_type": "vllm",
          "input_size": 4096,
          "model_path": "",
          "weight": 1.0,
          "keep_alive": null,
          "tool_calling": false
        }
      ],
      "providers_sleep": [
        {
          "id": "gemma3_12b-vllm-66:7000",
          "api_host": "http://192.168.100.66:7000/",
          "api_token": "",
          "api_type": "vllm",
          "input_size": 4096,
          "model_path": "",
          "weight": 0.1,
          "keep_alive": null,
          "tool_calling": false
        }
        /* … more sleeping providers … */
      ]
    },
    "google/gemini-2.5-flash-lite": {
      "providers": [
        {
          "id": "google_gemini_2_5-flash-lite",
          "api_host": "https://generativelanguage.googleapis.com/v1beta/openai/",
          "api_token": "YOUR_GOOGLE_API_KEY",
          "api_type": "openai",
          "input_size": 512000,
          "model_path": "gemini-2.5-flash-lite",
          "keep_alive": null,
          "tool_calling": true
        }
      ]
    }
  },
  "openai_models": {
    "openai/gpt-3.5-turbo-0125": {
      "providers": [
        {
          "id": "openai-gpt3_5-t-0125",
          "api_host": "https://api.openai.com",
          "api_token": "YOUR_OPENAI_KEY",
          "api_type": "openai",
          "input_size": 256000,
          "model_path": "gpt-3.5-turbo-0125",
          "keep_alive": null,
          "tool_calling": false
        }
      ]
    }
    /* … other OpenAI/Ollama models … */
  },
  "qwen_models": {
    "qwen3-coder:30b": {
      "providers": [
        {
          "id": "qwen3-coder-30b-66:11434",
          "api_host": "http://192.168.100.66:11434",
          "api_token": "",
          "api_type": "ollama",
          "input_size": 256000,
          "model_path": "",
          "keep_alive": "35m",
          "tool_calling": true
        }
        /* … second provider … */
      ]
    }
  },
  "active_models": {
    "google_models": [
      "google/gemma-3-12b-it",
      "google/gemini-2.5-flash-lite"
    ],
    "openai_models": [
      "openai/gpt-3.5-turbo-0125"
    ],
    "qwen_models": [
      "qwen3-coder:30b"
    ]
  }
}
```

> **Tip:**  
> *Keep the file name configurable through the environment variable `LLM_ROUTER_MODELS_CONFIG` (the default
is `resources/configs/models-config.json`).*

---  

## 🎉 Summary

* **`models-config.json`** is the single source of truth for every LLM provider used by the router.
* **`active_models`** decides which models are exposed.
* **`ModelHandler` + `ApiModelConfig`** read the file, pick a provider according to the configured strategy, and hand
  you a ready‑to‑use `ApiModel` instance.
* The sample configuration below can be copied and tweaked to fit your own deployment.

Feel free to edit this file whenever you add new providers or change load‑balancing weights – the router picks up the
changes on the next start (or after re‑loading the handler in a running process). Happy modeling!