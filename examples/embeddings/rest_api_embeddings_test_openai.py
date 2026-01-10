import os
import argparse
import requests
from typing import List

# --------------------------------------------------------------
# Configuration
# --------------------------------------------------------------
# Base URL of an OpenAI‑compatible service (e.g., LLM‑Router, local server)
BASE_URL = os.getenv("LLM_ROUTER_URL", "http://localhost:8080")

# The OpenAI SDK requires an API key – we provide a placeholder.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sk-placeholder")
client = None  # will be initialised in `init_client()`

# Example texts that will be embedded
DEFAULT_TEXTS = [
    "Alice has a cat, and the cat has Alice.",
    "The quick brown fox jumps over the lazy dog.",
    "Artificial intelligence is changing the world for the better.",
]


# --------------------------------------------------------------
# Initialise OpenAI client
# --------------------------------------------------------------
def init_client() -> None:
    """
    Creates a global OpenAI client that directs requests to our
    custom endpoint ``/v1/embeddings``.
    """
    global client
    from openai import OpenAI

    # `base_url` points to the server; the SDK automatically appends ``/v1``.
    client = OpenAI(
        api_key=OPENAI_API_KEY,
        base_url=BASE_URL.rstrip("/"),  # e.g., http://localhost:8080
    )


# --------------------------------------------------------------
# Optional detection of embedding models
# --------------------------------------------------------------
def get_active_embedding_models() -> List[str]:
    """Fetches a list of models flagged as ``is_embedding`` from /api/tags."""
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
# Retrieve embeddings
# --------------------------------------------------------------
def test_embeddings(model: str, texts: List[str]) -> None:
    """Sends an embedding request and prints the returned vectors."""
    print("\n" + "=" * 60)
    print(f"Testing model: {model}")
    print("=" * 60)

    try:
        # SDK returns an object with a ``data`` attribute – a list of
        # ``Embedding`` objects that contain the ``embedding`` field (list of floats).
        response = client.embeddings.create(model=model, input=texts)

        # Some services may return an empty ``data`` list.
        # In that case, attempt to read the raw JSON payload.
        if not getattr(response, "data", None):
            raw = response.model_dump()
            raise ValueError(f"No embedding data – raw payload: {raw}")

        embeddings = [item.embedding for item in response.data]

        print(f"✅ Success! Received {len(embeddings)} embeddings.")
        for i, vec in enumerate(embeddings):
            dim = len(vec)
            preview = str(vec[:5]) + "..." if dim > 5 else str(vec)
            print(f"  Text {i + 1} [dim: {dim}]: {preview}")

    except Exception as e:
        # SDK raises ``openai.APIError`` or ``ValueError``.
        # Print the full error to see what the backend returned.
        print(f"❌ Exception while requesting embeddings: {e}")


# --------------------------------------------------------------
# CLI entry point
# --------------------------------------------------------------
def main() -> None:
    global BASE_URL
    parser = argparse.ArgumentParser(
        description="Utility to test embeddings via an OpenAI‑compatible API."
    )
    parser.add_argument(
        "--models", nargs="+", help="Explicit list of model names to test."
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
