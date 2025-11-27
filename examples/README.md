# Integration Examples with LLM Router

This directory contains example boilerplates that demonstrate how easy it is to integrate popular LLM libraries with the
router by simply switching the host.

## Available Examples

- **[LlamaIndex](llamaindex_example.py)** – Integration with LlamaIndex (GPT Index)
- **[LangChain](langchain_example.py)** – Integration with LangChain
- **[OpenAI SDK](openai_example.py)** – Direct integration with the OpenAI Python SDK
- **[LiteLLM](litellm_example.py)** – Integration with LiteLLM
- **[Haystack](haystack_example.py)** – Integration with Haystack

## Core Principle

All examples work on the same principle: **just change `base_url` / `api_base` to the address of your router**, and the
router will automatically:

1. ✅ Distribute traffic among available providers
2. ✅ Perform load balancing
3. ✅ Provide health checking
4. ✅ Supply monitoring and metrics
5. ✅ Handle streaming and non‑streaming responses

## Quick Start

Each example can be run directly:

```shell script
# LlamaIndex
python examples/llamaindex_example.py

# LangChain
python examples/langchain_example.py

# OpenAI SDK
python examples/openai_example.py

# LiteLLM
python examples/litellm_example.py

# Haystack
python examples/haystack_example.py
```

## Example Structure

Each example includes:

1. **Basic configuration** – how to point the library at the router
2. **Streaming** – handling streaming responses
3. **Non‑streaming** – handling full responses
4. **Error handling** – managing errors

## Additional Information

Learn more about the router:

- [Main README](../README.md)
- [API Documentation](../llm_router_api/README.md)
- [Endpoints Overview](../llm_router_api/endpoints/README.md)
- [Load‑Balancing Strategies](../llm_router_api/LB_STRATEGIES.md)