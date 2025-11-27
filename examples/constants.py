import os

HOST = os.getenv("LLM_ROUTER_HOST", "http://localhost:8080")

# ----------------------------------------------------------------------
# MODELS – these are the model identifiers that are defined in the
# llm‑router configuration.  They are the logical names the router expects.
# ----------------------------------------------------------------------
MODELS = ["google/gemma-3-12b-it", "gpt-oss:120b"]


# ----------------------------------------------------------------------
# OPENAI_TO_CUSTOM – mapping required by LlamaIndex.
# Keys are model names that the LlamaIndex ``OpenAI`` wrapper understands,
# values are the corresponding logical names from ``MODELS`` above.
# ----------------------------------------------------------------------
OPENAI_TO_CUSTOM = {
    "gpt-3.5-turbo": "google/gemma-3-12b-it",
    "gpt-4": "gpt-oss:120b",
}
