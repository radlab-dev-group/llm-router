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
            "content": "Jesteś pomocnym agentem na czacie.",
        },
        {
            "role": "user",
            "content": "Jak się masz?",
        },
    ],
}

conv_with_model_payload = {
    "model_name": "",
    "user_last_statement": "Jaka jest kategoria tekstu: Ala ma kota i psa.",
}

# ----------------------------------------------------------------------
# Endpoint tests
# ----------------------------------------------------------------------


class Ollama:
    @staticmethod
    def test_ollama_home_ep(_, debug: bool = False) -> None:
        """Health‑check endpoint ``/`` (GET)."""
        resp = _get("/")
        if debug:
            print("Ollama home:", resp.text)

    @staticmethod
    def test_ollama_tags_ep(_, debug: bool = False) -> None:
        """Tags endpoint ``/api/tags`` (GET)."""
        resp = _get("/api/tags")
        if debug:
            print("Ollama tags:", resp.json())

    @staticmethod
    def test_lmstudio_models(_, debug: bool = False) -> None:
        """LM‑Studio models list endpoint ``/v0/models`` (GET)."""
        resp = _get("/api/v0/models")
        if debug:
            print("LM Studio models:", resp.json())

    @staticmethod
    def test_ollama_chat_no_stream(model_name: str, debug: bool = False) -> None:
        """Chat completion endpoint ``/api/chat`` (POST)."""
        payload = ollama_payload.copy()
        payload["stream"] = False
        payload["model"] = model_name
        resp = _post("/api/chat", payload)
        if debug:
            print("Api chat:", resp.json())

    @staticmethod
    def test_ollama_chat_stream(model_name: str, debug: bool = False) -> None:
        """Chat completion endpoint ``/api/chat`` with streaming (POST, stream=True)."""
        payload = ollama_payload.copy()
        payload["stream"] = True
        payload["model"] = model_name
        url = f"{BASE_URL.rstrip('/')}/api/chat"
        with requests.post(url, json=payload, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            if debug:
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
                        if debug:
                            print(content_str, end="", flush=True)
                    elif debug:
                        print(data)
        if debug:
            print("")


class VLLM:
    @staticmethod
    def test_chat_vllm_no_stream(model_name: str, debug: bool = False) -> None:
        """Chat completion endpoint ``/api/chat`` (POST)."""
        payload = ollama_payload.copy()
        payload["stream"] = False
        payload["model"] = model_name
        resp = _post("/v1/chat/completions", payload)
        if debug:
            print("VLLM chat:", resp.json())

    @staticmethod
    def test_chat_vllm_stream(model_name: str, debug: bool = False) -> None:
        """Chat completion endpoint with streaming from an external VLLM server."""
        payload = ollama_payload.copy()
        payload["stream"] = True
        payload["model"] = model_name
        url = f"{BASE_URL.rstrip('/')}/v1/chat/completions"

        with requests.post(url, json=payload, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            if debug:
                print("Streaming chat response:")
            for line in resp.iter_lines():
                if not line:
                    continue

                if isinstance(line, bytes):
                    line = line.decode("utf-8", errors="replace")

                cleaned = line.lstrip("data: ").strip()
                try:
                    data = json.loads(cleaned)
                except json.JSONDecodeError:
                    if "[DONE]" in line.strip().upper():
                        continue
                    print(f"Unparsable line: {line}")
                    continue

                if "choices" in data and data["choices"]:
                    delta = data["choices"][0].get("delta", {})
                    content = delta.get("content")
                    if content and debug:
                        print(content, end="", flush=True)
                    if delta.get("finish_reason"):
                        break
                elif debug:
                    print(data)
        if debug:
            print("\n")


class Builtin:
    @staticmethod
    def parse_response(response):
        j_resp = response.json()
        if not j_resp.get("status", True):
            if "body" in j_resp:
                j_resp = j_resp["body"]
            raise Exception(json.dumps(j_resp))

    @staticmethod
    def test_builtin_ping(_, debug: bool = False) -> None:
        """Tags endpoint ``/api/ping`` (GET)."""
        resp = _get("/api/ping")
        if debug:
            print("Builtin ping:", resp.json())

    @staticmethod
    def test_builtin_con_with_model_no_stream(
        model_name: str, debug: bool = False
    ) -> None:
        """Chat completion endpoint ``/api/conversation_with_model`` (POST)."""
        payload = conv_with_model_payload.copy()
        payload["model_name"] = model_name
        resp = _post("/api/conversation_with_model", payload)
        if debug:
            print("Builtin conversation_with_model:", resp.json())
        Builtin.parse_response(resp)

    @staticmethod
    def test_builtin_ext_con_with_model_no_stream(
        model_name: str, debug: bool = False
    ) -> None:
        payload = conv_with_model_payload.copy()
        payload["model_name"] = model_name
        payload["system_prompt"] = "Odpowiadaj jak mistrz Yoda."
        resp = _post("/api/extended_conversation_with_model", payload)
        if debug:
            print("Builtin extended_conversation_with_model:", resp.json())
        Builtin.parse_response(resp)


def run_all_tests() -> None:
    """Execute all endpoint tests sequentially."""
    models = {
        "ollama120": "gpt-oss:120b",
        "external_model_name": "google/gemini-2.0-flash",
        "vllm_model": "google/gemma-3-12b-it",
    }

    test_functions = [
        # test_lmstudio_models <- not fully integrated,
        [Ollama.test_ollama_home_ep, "ollama120", False],
        [Ollama.test_ollama_tags_ep, "ollama120", False],
        [Ollama.test_ollama_chat_no_stream, "ollama120", False],
        [Ollama.test_ollama_chat_stream, "ollama120", False],
        [VLLM.test_chat_vllm_no_stream, "vllm_model", False],
        [VLLM.test_chat_vllm_stream, "vllm_model", False],
        [Builtin.test_builtin_ping, "vllm_model", False],
        [Builtin.test_builtin_con_with_model_no_stream, "vllm_model", False],
        [Builtin.test_builtin_ext_con_with_model_no_stream, "vllm_model", False],
    ]
    for fn, model_name, debug in test_functions:
        try:
            print(f"Running {fn.__name__} ...")
            fn(models[model_name], debug)
        except Exception as e:
            print(f"❌ {fn.__name__} failed: {e}")
        else:
            print(f"✅ {fn.__name__} succeeded")
        print("-" * 40)


if __name__ == "__main__":
    run_all_tests()
