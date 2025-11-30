# vLLM + `google/gemma‑3‑12b‑it` – Quick‑Start Guide (Ubuntu)

> **Prerequisites**
> - Ubuntu 20.04 or newer
> - Python 3.10 (our project uses 3.10.6)
> - `virtualenv` (installed)
> - CUDA 11.8 + GPU **or** a CPU‑only setup

---  

## 1️⃣ Create & activate a virtual environment

```
mkdir -p ~/vllm-gemma && cd ~/vllm-gemma
python3 -m venv .venv
source .venv/bin/activate
```

> This creates an optional project directory, sets up a Python virtual environment in `.venv`, and activates it (you’ll
> see `(.venv)` in the prompt).

---  

## 2️⃣ Install **vLLM**

```
pip install --upgrade pip
pip install "vllm[cuda]"
```

> The above installs the latest `pip` and then installs **vLLM** with GPU support (the appropriate CUDA libraries are
> detected automatically).  
> If you have no GPU, install the CPU‑only version instead: `pip install vllm[cpu]`.

---  

### Verify the installation

```
python -c "import vllm; print(vllm.__version__)"
```

You should see a version string such as `0.11.2`.

---  

## 3️⃣ Obtain the model `google/gemma-3-12b-it`

```
mkdir -p ./google/gemma-3-12b-it
pip install huggingface_hub
hf download google/gemma-3-12b-it \
    --local-dir ./google/gemma-3-12b-it \
    --repo-type model
```

> This creates a folder for the model, installs the Hugging Face CLI, and downloads the model files into
`./google/gemma-3-12b-it`. The files are cached under `~/.cache/huggingface/hub` by default; you can keep a local copy
> to avoid re‑downloads.

---  

## 4️⃣ Run the **vLLM** server

Copy the ready‑to‑use Bash script
(`llm-router/examples/quickstart/google-gemma3-12b-it/run-gemma-3-12b-it-vllm.sh`)
to directory wgen the vLLM will be started with the Gemma 3 model.

```
cp path/to/llm-router/examples/quickstart/google-gemma3-12b-it/run-gemma-3-12b-it-vllm.sh .
bash run-gemma-3-12b-it-vllm.sh
```

> **Tip:** Run the server inside a `tmux` or `screen` session so it stays alive even if you disconnect from the
> terminal.

---  

## 5️⃣ Test the endpoint

> > **INFO**: `curl` and `jq` are system utilities.

```
curl http://localhost:7000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
        "model": "google/gemma-3-12b-it",
        "messages": [{"role": "user", "content": "Hello, how are you?"}],
        "max_tokens": 100
      }' | jq
```

You should receive a JSON response containing the model’s generated text, for example:

```json
{
  "id": "chatcmpl-e30bed0db9f9440a8aec14bd287ca63d",
  "object": "chat.completion",
  "created": 1764516430,
  "model": "google/gemma-3-12b-it",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! I'm doing well, thank you for asking! As an AI, I don't experience feelings like humans do, but everything is running smoothly and I'm ready to chat. 😊\n\nHow are *you* doing today?",
        "refusal": null,
        "annotations": null,
        "audio": null,
        "function_call": null,
        "tool_calls": [],
        "reasoning": null,
        "reasoning_content": null
      },
      "logprobs": null,
      "finish_reason": "stop",
      "stop_reason": 106,
      "token_ids": null
    }
  ],
  "service_tier": null,
  "system_fingerprint": null,
  "usage": {
    "prompt_tokens": 15,
    "total_tokens": 66,
    "completion_tokens": 51,
    "prompt_tokens_details": null
  },
  "prompt_logprobs": null,
  "prompt_token_ids": null,
  "kv_transfer_params": null
}
```

---  

## 6️⃣ Handy tips

| Topic              | Recommendation                                                                                                                |
|--------------------|-------------------------------------------------------------------------------------------------------------------------------|
| **Memory**         | `google/gemma‑3‑12b‑it` needs ~24GB VRAM. Use `--cpu-offload` (if supported) for larger models or when GPU memory is limited. |
| **Cache location** | Set `HF_HOME=$PWD/.cache/huggingface` to keep all model files inside the project directory.                                   |
| **Parallelism**    | Export `TOKENIZERS_PARALLELISM=false` to silence tokenizer warnings.                                                          |
| **GPU selection**  | `export CUDA_VISIBLE_DEVICES=0` (or another index) when multiple GPUs are present.                                            |
| **Update**         | `pip install -U vllm` refreshes the library; the next server start will pull newer model files if available.                  |
| **Deactivate**     | When done, simply run `deactivate` to leave the virtual environment.                                                          |

---  

## 🎉 All set!

You now have a fully functional OpenAI‑compatible API powered by **vLLM** and the **google/gemma‑3‑12b‑it** model.
If you encounter any issues (CUDA errors, version mismatches, etc.), feel free to ask for help. Happy generating!