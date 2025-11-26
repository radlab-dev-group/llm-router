import os

HOST = os.getenv("LLM_ROUTER_HOST", "http://localhost:8080")

MODELS = ["google/gemma-3-12b-it", "gpt-oss:20b"]
