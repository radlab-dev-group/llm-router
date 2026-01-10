import os
import requests
import argparse

from typing import List

# Base configuration
BASE_URL = os.getenv("LLM_ROUTER_URL", "http://localhost:8080")
DEFAULT_TEXTS = [
    "Alice has a cat, and the cat has Alice.",
    "The quick brown fox jumps over the lazy dog.",
    "Artificial intelligence is changing the world for the better.",
]


def get_active_embedding_models() -> List[str]:
    """Fetch the list of active embedding models from the API."""
    try:
        url = f"{BASE_URL.rstrip('/')}/api/tags"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()

        embedding_models: List[str] = []
        for model in data.get("models", []):
            if model.get("is_embedding"):
                embedding_models.append(model["id"])

        return embedding_models
    except Exception as e:
        print(f"Error while fetching models: {e}")
        return []


def test_embeddings(model: str, texts: List[str]):
    """Test the embedding endpoint for a given model and list of texts."""
    print(f"\n{'=' * 60}")
    print(f"Testing model: {model}")
    print(f"{'=' * 60}")

    # Try both possible endpoint versions
    endpoints = ["/api/embeddings", "/v1/embeddings"]

    for ep in endpoints:
        url = f"{BASE_URL.rstrip('/')}{ep}"
        print(f"\nChecking endpoint: {ep}")

        payload = {"model": model, "input": texts}

        try:
            response = requests.post(url, json=payload, timeout=30)
            if response.status_code == 200:
                result = response.json()

                embeddings_data = result.get("embeddings", [])

                print(f"✅ Success! Received {len(embeddings_data)} embeddings.")

                for i, vec in enumerate(embeddings_data):
                    dim = len(vec)
                    preview = str(vec[:5]) + "..." if dim > 5 else str(vec)
                    print(f"  Text {i + 1} [dim: {dim}]: {preview}")
            else:
                print(f"❌ HTTP error {response.status_code}: {response.text}")
        except Exception as e:
            print(f"❌ Exception while requesting {ep}: {e}")


def main():
    global BASE_URL
    parser = argparse.ArgumentParser(
        description="Simple utility to test embeddings via the LLM‑Router API."
    )
    parser.add_argument("--models", nargs="+", help="List of model names to test.")
    parser.add_argument("--url", help=f"Base API URL (default: {BASE_URL})")

    args = parser.parse_args()

    if args.url:
        BASE_URL = args.url

    target_models = args.models
    if not target_models:
        print(
            "No models specified on the command line. Attempting auto‑detection..."
        )
        target_models = get_active_embedding_models()

    if not target_models:
        print(
            "No active embedding models found. Use --models to specify them manually."
        )
        return

    print(f"Starting tests for models: {', '.join(target_models)}")
    print(f"Using test texts ({len(DEFAULT_TEXTS)}):")
    for i, t in enumerate(DEFAULT_TEXTS):
        print(f"  {i + 1}. {t}")

    for model in target_models:
        test_embeddings(model, DEFAULT_TEXTS)


if __name__ == "__main__":
    main()
