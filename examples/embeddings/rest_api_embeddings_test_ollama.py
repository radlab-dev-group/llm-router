import os
import argparse
import requests
from typing import List

# --------------------------------------------------------------
# Configuration
# --------------------------------------------------------------
# Default Ollama server address (compatible with OpenAI‑compatible API)
BASE_URL = os.getenv("LLM_ROUTER_URL", "http://localhost:8080")

# The OpenAI SDK expects an API key – we provide a placeholder.
# It is not used by Ollama, but keeping the key maintains compatibility
# with the OpenAI‑compatible interface.
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "sk-placeholder")  # not used

# Example texts for embedding
DEFAULT_TEXTS = [
    "Alice has a cat, and the cat has Alice.",
    "The quick brown fox jumps over the lazy dog.",
    "Artificial intelligence is changing the world for the better.",
]


# --------------------------------------------------------------
# Initialise Ollama client (imitating OpenAI client)
# --------------------------------------------------------------
def init_client() -> None:
    """
    Creates a global `client` object based on the `ollama` library.
    No API key is required – only the host address.
    """
    global client
    import ollama

    # `host` points to the server; the SDK does not append `/v1`,
    # so we strip any trailing slash.
    client = ollama.Client(host=BASE_URL.rstrip("/"))


# --------------------------------------------------------------
# Detect available embedding models
# --------------------------------------------------------------
def get_active_embedding_models() -> List[str]:
    """Fetches a list of models flagged as `is_embedding` from /api/tags."""
    try:
        url = f"{BASE_URL.rstrip('/')}/api/tags"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        return [
            model["id"]
            for model in data.get("models", [])
            if model.get("is_embedding")
        ]
    except Exception as e:
        print(f"Error while fetching models: {e}")
        return []


# --------------------------------------------------------------
# Retrieve embeddings using Ollama
# --------------------------------------------------------------
def test_embeddings(model: str, texts: List[str]) -> None:
    """
    Sends an embedding request to Ollama and prints the returned vectors.
    The interface mirrors `openai.embeddings.create`.
    """
    print("\n" + "=" * 60)
    print(f"Testing model: {model}")
    print("=" * 60)

    try:
        # Ollama returns a dict {"embeddings": [[...], [...]]}
        result = client.embed(model=model, input=texts)

        embeddings = result.get("embeddings", [])
        if not embeddings:
            raise ValueError("No embeddings returned by Ollama.")

        print(f"✅ Success! Received {len(embeddings)} embeddings.")
        for i, vec in enumerate(embeddings):
            dim = len(vec)
            preview = str(vec[:5]) + "..." if dim > 5 else str(vec)
            print(f"  Text {i + 1} [dim: {dim}]: {preview}")

    except Exception as e:
        # Any errors (network, missing model, etc.) are printed.
        print(f"❌ Exception while requesting embeddings: {e}")


# --------------------------------------------------------------
# CLI entry point
# --------------------------------------------------------------
def main() -> None:
    global BASE_URL
    parser = argparse.ArgumentParser(
        description="Utility to test embeddings via an Ollama‑compatible API."
    )
    parser.add_argument(
        "--models",
        nargs="+",
        help="Explicit list of model names to test.",
    )
    parser.add_argument(
        "--url",
        help=f"Base API URL (overrides LLM_ROUTER_URL, default: {BASE_URL})",
    )
    args = parser.parse_args()

    # Allow overriding the URL from the command line
    if args.url:
        BASE_URL = args.url.rstrip("/")
    init_client()  # client must be ready before use

    # If no models are supplied, try to infer them from /api/tags
    target_models = args.models
    if not target_models:
        print("No models supplied – trying to auto‑detect from the router...")
        target_models = get_active_embedding_models()

    if not target_models:
        print(
            "No embedding models found. Provide them with --models or ensure the router "
            "exposes /api/tags with `is_embedding` flags."
        )
        return

    print(f"Testing models: {', '.join(target_models)}")
    print(f"Using {len(DEFAULT_TEXTS)} test texts:")
    for i, txt in enumerate(DEFAULT_TEXTS, 1):
        print(f"  {i}. {txt}")

    for model in target_models:
        test_embeddings(model, DEFAULT_TEXTS)


if __name__ == "__main__":
    main()
