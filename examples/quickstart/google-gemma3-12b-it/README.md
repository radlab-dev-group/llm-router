# 🚀 Quick‑Start Guide for `google/gemma-3-12b‑it` with **vLLM** & **LLM‑Router**

This guide walks you through:

1. **Installing vLLM** and the `google/gemma‑3‑12b‑it` model.
2. **Installing LLM‑Router** (the API gateway).
3. **Running the router** with the model configuration provided in `models-config.json`.

All commands assume you are working on a Unix‑like system (Linux/macOS) with **Python 3.10.6** and `virtualenv`
available.

---

## 📋 Prerequisites

| Requirement | Details                                                                                |
|-------------|----------------------------------------------------------------------------------------|
| **OS**      | Ubuntu 20.04 + (or any recent Linux/macOS)                                             |
| **Python**  | 3.10.6 (project’s default)                                                             |
| **GPU**     | CUDA 11.8 + (≥ 24 GB VRAM) **or** CPU‑only setup                                       |
| **Tools**   | `git`, `curl`, `jq` (optional but handy for testing)                                   |
| **Network** | Ability to pull Docker images / PyPI packages and download the model from Hugging Face |

---

## 1️⃣ Set up a virtual environment

```shell script
# Create a directory for the whole demo (optional)
mkdir -p ~/gemma3-demo && cd $_

# Initialise the venv
python3 -m venv .venv
source .venv/bin/activate

# Upgrade pip (always a good idea)
pip install --upgrade pip
```

---

## 2️⃣ Install **vLLM** and download the Gemma 3 model

> **See the full step‑by‑step instructions in** [`VLLM.md`](./VLLM.md).

---

## 3️⃣ Run the **vLLM** server

Copy the helper script (or run the command manually) inside the demo directory:

```shell script
# If you have the script `run-gemma-3-12b-it-vllm.sh` in the repo:
cp path/to/llm-router/examples/quickstart/google-gemma3-12b-it/run-gemma-3-12b-it-vllm.sh .
chmod +x run-gemma-3-12b-it-vllm.sh

# Start the server (you may want to use tmux/screen)
./run-gemma-3-12b-it-vllm.sh
```

The server will listen on **`http://0.0.0.0:7000`** and expose an OpenAI‑compatible endpoint at `/v1/chat/completions`.

You can quickly test it:

```shell script
curl http://localhost:7000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
        "model": "google/gemma-3-12b-it",
        "messages": [{"role": "user", "content": "Hello, how are you?"}],
        "max_tokens": 100
      }' | jq
```

You should receive a JSON payload with the model’s generated text.

---

## 4️⃣ Install **LLM‑Router**

### Local install

```shell script
# Clone the router repository (if you haven’t already)
git clone https://github.com/radlab-dev-group/llm-router.git
cd llm-router

# Install the core library + API wrapper (includes the REST server)
pip install .[api]

# (Optional) Install Prometheus metrics support
pip install .[api,metrics]
```

> **Note:** The router uses the same virtual environment you created earlier, so all dependencies stay isolated.

[//]: # (### Docker based install)

---

## 5️⃣ Prepare the router configuration

The example repository already ships a [`models-config.json`](./models-config.json) that points to the locally running
vLLM instance:

```json
{
  "google_models": {
    "google/gemma-3-12b-it": {
      "providers": [
        {
          "id": "gemma3_12b-vllm-local:7000",
          "api_host": "http://localhost:7000/",
          "api_type": "vllm",
          "input_size": 56000,
          "weight": 1.0
        }
      ]
    }
  },
  "active_models": {
    "google_models": [
      "google/gemma-3-12b-it"
    ]
  }
}
```

Copy it (or edit the path) to the router’s `resources/configs/` directory:

```shell script
mkdir -p resources/configs
cp path/to/google-gemma3-12b-it/models-config.json resources/configs/
```

---

## 6️⃣ Run the **LLM‑Router**

### Local Gunicorn

The helper script `run-rest-api-gunicorn.sh` sets a sensible default environment. You can use it directly or export the
variables yourself.

```shell script
# Make the script executable (if needed)
chmod +x path/to/run-rest-api-gunicorn.sh

# Run the router
./run-rest-api-gunicorn.sh
```

Key environment variables (already defined in the script) you may want to adjust:

| Variable                      | Default                                | Meaning                                    |
|-------------------------------|----------------------------------------|--------------------------------------------|
| `LLM_ROUTER_SERVER_TYPE`      | `gunicorn`                             | Server backend (gunicorn, flask, waitress) |
| `LLM_ROUTER_SERVER_PORT`      | `8080`                                 | Port on which the router listens           |
| `LLM_ROUTER_MODELS_CONFIG`    | `resources/configs/models-config.json` | Path to the JSON file above                |
| `LLM_ROUTER_PROMPTS_DIR`      | `resources/prompts`                    | Prompt‑template directory (optional)       |
| `LLM_ROUTER_BALANCE_STRATEGY` | `first_available`                      | Load‑balancing strategy                    |
| `LLM_ROUTER_USE_PROMETHEUS`   | `1` (if you installed metrics)         | Enable `/api/metrics` endpoint             |

After the script starts, the router will be reachable at **`http://0.0.0.0:8080/api`**.
A full list of available environment variables can be found in
the [environment description](../../../llm_router_api/README.md#environment-variables)
---

## 7️⃣ Test the full stack (router → vLLM)

```shell script
curl http://localhost:8080/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
        "model": "google/gemma-3-12b-it",
        "messages": [{"role": "user", "content": "Tell me a short joke."}],
        "max_tokens": 80
      }' | jq
```

The request goes through **LLM‑Router**, which forwards it to the local vLLM server, and you receive the generated
response.

---

## 🚀 Running the examples

The [`examples/`](../../../examples) folder already contains detailed README files and individual script doc‑strings
that explain how each library (LangChain, LlamaIndex, OpenAI SDK, LiteLLM, Haystack) works with the LLM‑Router.

**What you need to do**

1. **Set the router address** – export `LLM_ROUTER_HOST` in the environment (or edit `examples/constants.py`) so that

```python
HOST = "http://localhost:8080/api"
```

matches the URL where you started the router (`run-rest-api-gunicorn.sh`).

2. **(Optional) Synchronise model names** – ensure the `MODELS` list in `constants.py` reflects the logical model
   identifiers you defined in `resources/configs/models-config.json`.

3. **Install the example dependencies**

```shell script
pip install -r examples/requirements.txt
```

4. **Run the examples** – each script can be executed directly, e.g.:

```shell script
python examples/langchain_example.py
python examples/llamaindex_example.py
python examples/openai_example.py
python examples/litellm_example.py
python examples/haystack_example.py
```

All other configuration details (prompt handling, streaming, multi‑model usage, error handling, etc.) are documented
inside the individual example files and the [`examples/README.md`](../../README.md) / [
`examples/README_LLAMAINDEX.md`](../../README_LLAMAINDEX.md) files. Adjust only the `HOST`
(and optionally `MODELS`) and the examples will automatically route their requests through the running LLM‑Router.

---

## 🎉 What’s next?

- **Prometheus**: If you enabled metrics, add the router’s `/api/metrics` endpoint to your Prometheus scrape config.
- **Guardrails & Masking**: Set the `LLM_ROUTER_FORCE_MASKING`, `LLM_ROUTER_FORCE_GUARDRAIL_REQUEST`, etc., to activate
  data‑protection plugins.
- **Multiple providers**: Extend `models-config.json` with additional providers (e.g., Ollama, OpenAI) and experiment
  with different load‑balancing strategies.

---

Enjoy your local `gemma-3-12b‑it` deployment powered by vLLM and LLM‑Router!

---