"""
LlamaIndex Integration Example

Demonstrates how to integrate LlamaIndex with an LLM Router.
Simply change the base_url in the constants module!


"openai_models": {
    "gpt-3.5-turbo": {
      "providers": [
        {
          "id": "gpt_35_turbo-gemma3_12b-vllm-71:7000",
          "api_host": "http://192.168.100.71:7000/",
          "api_token": "",
          "api_type": "vllm",
          "input_size": 4096,
          "model_path": "google/gemma-3-12b-it",
          "weight": 1.0
        },
        {
          "id": "gpt_35_turbo-gemma3_12b-vllm-71:7001",
          "api_host": "http://192.168.100.71:7001/",
          "api_token": "",
          "api_type": "vllm",
          "input_size": 4096,
          "model_path": "google/gemma-3-12b-it",
          "weight": 1.0
        }
      ]
    },
    "gpt-4": {
      "providers": [
        {
          "id": "gpt-4-gpt-oss-20b-ollama-66:11434",
          "api_host": "http://192.168.100.66:11434",
          "api_token": "",
          "api_type": "ollama",
          "input_size": 256000,
          "model_path": "gpt-oss:120b"
        }
      ]
    }
}

(...)

"active_models": {
    (...)
    "openai_models": [
      "gpt-3.5-turbo",
      "gpt-4",
      (...)
    ]
  }
(...)
"""

from llama_index.llms.openai import OpenAI
from llama_index.core.llms import ChatMessage

from constants import HOST, MODELS

# Choose an OpenAI‑compatible model name (the first key in the mapping).
# This model name is guaranteed to be recognised by the OpenAI wrapper.
DEFAULT_OPENAI_MODEL = "gpt-3.5-turbo"
SECONDARY_OPENAI_MODEL = "gpt-4"


class LlamaIndexExamples:
    """
    Helper class that groups all LlamaIndex‑Router example calls.
    Usage:
        examples = LlamaIndexExamples()
        examples.basic_example()
    """

    def __init__(self, host: str = HOST):
        self.base_url = host
        self.models = MODELS

    # ------------ 1. Basic Example ------------
    def basic_example(self):
        """Basic example using LlamaIndex"""
        llm = OpenAI(
            model=DEFAULT_OPENAI_MODEL,
            api_base=self.base_url,
            api_key="not-needed",
        )
        response = llm.chat(
            messages=[
                ChatMessage(
                    role="system", content="You are a helpful AI assistant."
                ),
                ChatMessage(
                    role="user",
                    content="Explain what an LLM Router is in one sentence.",
                ),
            ]
        )
        print("Response:", response.message.content)
        return response

    # ------------ 2. Streaming Example ------------
    def streaming_example(self):
        """Streaming response example"""
        llm = OpenAI(
            model=DEFAULT_OPENAI_MODEL,
            api_base=self.base_url,
            api_key="not-needed",
        )
        messages = [
            ChatMessage(
                role="user", content="Write a short poem about programming."
            ),
        ]
        print("Streaming response:")
        for chunk in llm.stream_chat(messages):
            print(chunk.delta, end="", flush=True)
        print("\n")

    # ------------ 3. RAG Example ------------
    def rag_example(self):
        """Retrieval‑Augmented Generation example"""
        from llama_index.core import VectorStoreIndex, Document
        from llama_index.embeddings.openai import OpenAIEmbedding

        # Documents to index
        documents = [
            Document(
                text="LLM Router is an open‑source gateway for LLM infrastructure."
            ),
            Document(
                text="Router handles load balancing across multiple providers."
            ),
            Document(text="Supports OpenAI, Ollama, vLLM and other back‑ends."),
        ]

        # LLM via router
        llm = OpenAI(
            model=DEFAULT_OPENAI_MODEL,
            api_base=self.base_url,
            api_key="not-needed",
        )

        # Embeddings (router may expose an embedding endpoint)
        embed_model = OpenAIEmbedding(
            api_base=self.base_url,
            api_key="not-needed",
        )

        # Build index
        index = VectorStoreIndex.from_documents(
            documents,
            llm=llm,
            embed_model=embed_model,
        )

        # Query
        query_engine = index.as_query_engine()
        response = query_engine.query("What is an LLM Router?")
        print("RAG Response:", response)
        return response

    # ------------ 4. Multi‑Model Example ------------
    def multi_model_example(self):
        """Query multiple models via the router"""
        # First model (mapped through DEFAULT_OPENAI_MODEL)
        llm_gemma = OpenAI(
            model=DEFAULT_OPENAI_MODEL,
            api_base=self.base_url,
            api_key="not-needed",
        )
        # Second model uses the second entry from MODELS directly
        llm_qwen = OpenAI(
            model=SECONDARY_OPENAI_MODEL,
            api_base=self.base_url,
            api_key="not-needed",
        )
        question = "What is recursion?"

        print("Gemma response:")
        response1 = llm_gemma.complete(question)
        print(response1.text)

        print("\nQwen response:")
        response2 = llm_qwen.complete(question)
        print(response2.text)

    # ------------ 5. Error Handling Example ------------
    def error_handling_example(self):
        """Error handling example"""
        llm = OpenAI(
            model="nonexistent-model",
            api_base=self.base_url,
            api_key="not-needed",
        )
        try:
            response = llm.complete("Test")
            print(response.text)
        except Exception as e:
            print(f"Error caught: {type(e).__name__}: {e}")
            print(
                "Router returned an error – model does not exist in the configuration."
            )


if __name__ == "__main__":
    print("=" * 80)
    print("LlamaIndex + LLM Router Integration Examples")
    print("=" * 80)

    examples = LlamaIndexExamples()

    print("\n1. Basic Example")
    print("-" * 80)
    examples.basic_example()

    print("\n2. Streaming Example")
    print("-" * 80)
    examples.streaming_example()

    # TODO:
    # print("\n3. RAG Example")
    # print("-" * 80)
    # examples.rag_example()

    print("\n4. Multi‑Model Example")
    print("-" * 80)
    examples.multi_model_example()

    print("\n5. Error Handling Example")
    print("-" * 80)
    examples.error_handling_example()

    print("\n" + "=" * 80)
    print("All examples completed!")
    print("=" * 80)
