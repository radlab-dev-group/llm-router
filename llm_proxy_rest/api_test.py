import os
import json
import requests
from typing import Any, Dict

# Base URL of the llm‑proxy REST API.
# Can be overridden by the environment variable LLM_PROXY_URL.
BASE_URL = os.getenv("LLM_PROXY_URL", "http://192.168.100.66:8080")


def _post(path: str, payload: Dict[str, Any]) -> requests.Response:
    """Helper to POST JSON payload to ``BASE_URL + path``."""
    url = f"{BASE_URL.rstrip('/')}{path}"
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    return response


def _get(path: str) -> requests.Response:
    """Helper to GET ``BASE_URL + path``."""
    url = f"{BASE_URL.rstrip('/')}{path}"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response


# ----------------------------------------------------------------------
ollama_payload = {
    "model": "",
    "stream": False,
    "messages": [
        {
            "role": "system",
            "content": "Jesteś pomocnym agentem na czacie, odpowiadasz jak Yoda. Odpowiadaj długo.",
        },
        {"role": "user", "content": "Jak się masz?"},
    ],
}


# ----------------------------------------------------------------------
# Endpoint tests
# ----------------------------------------------------------------------
def test_ollama_home(_) -> None:
    """Health‑check endpoint ``/`` (GET)."""
    resp = _get("/")
    print("Ollama home:", resp.text)


def test_ollama_tags(_) -> None:
    """Tags endpoint ``/api/tags`` (GET)."""
    resp = _get("/api/tags")
    print("Ollama tags:", resp.json())


def test_lmstudio_models(_) -> None:
    """LM‑Studio models list endpoint ``/v0/models`` (GET)."""
    resp = _get("/api/v0/models")
    print("LM Studio models:", resp.json())


def test_chat_ollama_no_stream(model_name: str) -> None:
    """Chat completion endpoint ``/api/chat`` (POST)."""
    payload = ollama_payload.copy()
    payload["stream"] = False
    payload["model"] = model_name
    resp = _post("/api/chat", payload)
    print("Api chat:", resp.json())


def test_chat_ollama_stream(model_name: str) -> None:
    """Chat completion endpoint ``/api/chat`` with streaming (POST, stream=True)."""
    payload = ollama_payload.copy()
    payload["stream"] = True
    payload["model"] = model_name
    url = f"{BASE_URL.rstrip('/')}/api/chat"
    with requests.post(url, json=payload, timeout=30, stream=True) as resp:
        resp.raise_for_status()
        print("Streaming chat response:")
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    cleaned = line.lstrip("data: ").strip()
                    try:
                        data = json.loads(cleaned)
                    except json.JSONDecodeError:
                        data = line  # Fallback to raw line

                if "message" in data:
                    content_str = data["message"]["content"]
                    print(content_str, end="", flush=True)
                else:
                    print(data)
    print("")


def test_chat_vllm_no_stream(model_name: str) -> None:
    """Chat completion endpoint ``/api/chat`` (POST)."""
    payload = ollama_payload.copy()
    payload["stream"] = False
    payload["model"] = model_name
    resp = _post("/v1/chat/completions", payload)
    print("Api chat:", resp.json())


def test_chat_vllm_stream(model_name: str) -> None:
    """Chat completion endpoint ``/api/chat`` (POST)."""
    payload = ollama_payload.copy()
    payload["stream"] = True
    payload["model"] = model_name
    url = f"{BASE_URL.rstrip('/')}/v1/chat/completions"
    with requests.post(url, json=payload, timeout=30, stream=True) as resp:
        resp.raise_for_status()
        print("Streaming chat response:")
        for line in resp.iter_lines(decode_unicode=True):
            if line:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    cleaned = line.lstrip("data: ").strip()
                    try:
                        data = json.loads(cleaned)
                    except json.JSONDecodeError:
                        data = line  # Fallback to raw line

                if "message" in data:
                    content_str = data["message"]["content"]
                    print(content_str, end="", flush=True)
                else:
                    print(data)
    print("")

    print("Api chat:", resp.json())


def run_all_tests() -> None:
    """Execute all endpoint tests sequentially."""
    test_functions = [
        # test_ollama_home,
        # test_ollama_tags,
        # test_lmstudio_models,
        # test_chat_ollama_no_stream,
        # test_chat_ollama_stream,
        test_chat_vllm_no_stream,
        # test_chat_vllm_stream,
    ]
    # Ollama model:
    # model_name = "gpt-oss:120b"

    # Gemini external api
    # model_name = "google/gemini-2.0-flash"

    # VLLM available via local API
    model_name = "google/gemma-3-12b-it"

    for fn in test_functions:
        try:
            print(f"Running {fn.__name__} ...")
            fn(model_name)
        except Exception as e:
            print(f"❌ {fn.__name__} failed: {e}")
        else:
            print(f"✅ {fn.__name__} succeeded")
        print("-" * 40)


if __name__ == "__main__":
    run_all_tests()
