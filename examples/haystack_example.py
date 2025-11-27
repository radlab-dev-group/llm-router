"""
Haystack Integration Example

Pokazuje jak zintegrować Haystack (deepset) z LLM Router.
Wymaga: pip install haystack-ai
"""

from typing import List, Optional

from haystack import Pipeline
from haystack.utils import Secret
from haystack.components.builders import PromptBuilder
from haystack.components.generators import OpenAIGenerator
from haystack.components.generators.chat import OpenAIChatGenerator
from haystack.components.routers import ConditionalRouter
from haystack.components.retrievers.in_memory import InMemoryBM25Retriever
from haystack.document_stores.in_memory import InMemoryDocumentStore
from haystack.dataclasses import ChatMessage, Document, StreamingChunk

from constants import HOST, MODELS


class HaystackExamples:
    """
    Klasa grupująca przykłady integracji Haystack z LLM Routerem.
    """

    def __init__(self, host: str = HOST):
        self.host = host
        self.default_model = MODELS[0]
        self.api_key = Secret.from_token("not-needed")

    # ---------------------------
    # 1. Basic Example
    # ---------------------------
    def basic_example(self):
        """Podstawowy przykład użycia generatora (completions)"""
        print(f"Using model: {self.default_model}")

        generator = OpenAIGenerator(
            api_key=self.api_key,
            api_base_url=self.host,
            model=self.default_model,
        )

        response = generator.run(
            prompt="Wyjaśnij czym jest LLM Router w jednym zdaniu."
        )
        print("Response:", response["replies"][0])
        return response

    # ---------------------------
    # 2. Pipeline Example
    # ---------------------------
    def pipeline_example(self):
        """Przykład budowy prostego potoku (Pipeline) z prompt template"""

        template = """
        Odpowiedz na pytanie na podstawie kontekstu.
        
        Kontekst: {{ context }}
        
        Pytanie: {{ question }}
        
        Odpowiedź:
        """

        pipe = Pipeline()

        # Komponenty
        pipe.add_component("prompt_builder", PromptBuilder(template=template))
        pipe.add_component(
            "llm",
            OpenAIGenerator(
                api_key=self.api_key,
                api_base_url=self.host,
                model=self.default_model,
            ),
        )

        # Łączenie
        pipe.connect("prompt_builder", "llm")

        # Uruchomienie
        print("Running pipeline...")
        result = pipe.run(
            {
                "prompt_builder": {
                    "context": "LLM Router to open-source gateway dla infrastruktury LLM. "
                    "Oferuje load balancing, health checks i monitoring.",
                    "question": "Jakie funkcje oferuje LLM Router?",
                }
            }
        )

        print("Pipeline result:", result["llm"]["replies"][0])
        return result

    # ---------------------------
    # 3. Chat Example
    # ---------------------------
    def chat_example(self):
        """Przykład trybu czatu (Chat Generators)"""

        generator = OpenAIChatGenerator(
            api_key=self.api_key,
            api_base_url=self.host,
            model=self.default_model,
        )

        messages = [
            ChatMessage.from_system("Jesteś ekspertem od systemów rozproszonych."),
            ChatMessage.from_user("Co to jest load balancing? Wyjaśnij krótko."),
        ]

        response = generator.run(messages=messages)
        print("Chat response:", response["replies"][0].text)
        return response

    # ---------------------------
    # 4. Streaming Example
    # ---------------------------
    def streaming_example(self):
        """Przykład streamowania odpowiedzi"""

        def print_chunk(chunk: StreamingChunk):
            print(chunk.content, end="", flush=True)

        generator = OpenAIChatGenerator(
            api_key=self.api_key,
            api_base_url=self.host,
            model=self.default_model,
            streaming_callback=print_chunk,
        )

        messages = [
            ChatMessage.from_user("Napisz krótki wiersz o kontenerach Docker."),
        ]

        print("Streaming response:")
        response = generator.run(messages=messages)
        print("\n")
        return response

    # ---------------------------
    # 5. RAG Pipeline Example
    # ---------------------------
    def rag_pipeline_example(self):
        """Przykład RAG (Retrieval-Augmented Generation)"""

        document_store = InMemoryDocumentStore()

        documents = [
            Document(
                content="LLM Router to open-source gateway dla infrastruktury LLM."
            ),
            Document(
                content="Router obsługuje load balancing między wieloma dostawcami (OpenAI, Ollama)."
            ),
            Document(content="Wspiera backendy takie jak vLLM, TGI i inne."),
            Document(
                content="Router oferuje streaming, health checks i monitoring metryk."
            ),
        ]
        document_store.write_documents(documents)

        template = """
        Na podstawie poniższych dokumentów odpowiedz na pytanie.
        Jeżeli odpowiedzi nie ma w dokumentach, napisz "Nie wiem".
        
        Dokumenty:
        {% for doc in documents %}
        - {{ doc.content }}
        {% endfor %}
        
        Pytanie: {{ question }}
        Odpowiedź:
        """

        pipe = Pipeline()
        pipe.add_component(
            "retriever", InMemoryBM25Retriever(document_store=document_store)
        )
        pipe.add_component("prompt_builder", PromptBuilder(template=template))
        pipe.add_component(
            "llm",
            OpenAIGenerator(
                api_key=self.api_key,
                api_base_url=self.host,
                model=self.default_model,
            ),
        )

        pipe.connect("retriever.documents", "prompt_builder.documents")
        pipe.connect("prompt_builder", "llm")

        query = "Jakie backendy wspiera router?"
        print(f"RAG Query: {query}")

        result = pipe.run(
            {
                "retriever": {"query": query},
                "prompt_builder": {"question": query},
            }
        )

        print("RAG result:", result["llm"]["replies"][0])
        return result

    # ---------------------------
    # 6. Multi-Model Pipeline
    # ---------------------------
    def multi_model_pipeline(self):
        """Przykład użycia dwóch różnych modeli"""

        model_1 = MODELS[0]
        model_2 = MODELS[1] if len(MODELS) > 1 else MODELS[0]

        print(f"Analyzer Model: {model_1}")
        print(f"Coder Model: {model_2}")

        analyzer = OpenAIGenerator(
            api_key=self.api_key,
            api_base_url=self.host,
            model=model_1,
        )

        coder = OpenAIGenerator(
            api_key=self.api_key,
            api_base_url=self.host,
            model=model_2,
        )

        print("\n--- Step 1: Analysis ---")
        analysis = analyzer.run(
            prompt="Opisz w jednym zdaniu teoretyczne działanie algorytmu QuickSort."
        )
        print("Analysis:", analysis["replies"][0])

        print("\n--- Step 2: Coding ---")
        code = coder.run(
            prompt="Napisz implementację QuickSort w Pythonie (sam kod)."
        )
        print("Code:", code["replies"][0])

        return analysis, code

    # ---------------------------
    # 7. Custom Parameters Example
    # ---------------------------
    def custom_parameters_example(self):
        """Przekazywanie parametrów generacji"""

        generator = OpenAIChatGenerator(
            api_key=self.api_key,
            api_base_url=self.host,
            model=self.default_model,
            generation_kwargs={
                "temperature": 0.1,
                "max_tokens": 150,
                "top_p": 0.9,
            },
        )

        messages = [
            ChatMessage.from_user(
                "Wymień 3 zalety architektury mikroserwisów (tylko lista)."
            ),
        ]

        response = generator.run(messages=messages)
        print("Response with params:", response["replies"][0].text)
        return response

    # ---------------------------
    # 8. Conditional Pipeline
    # ---------------------------
    def conditional_pipeline(self):
        """Przykład routingu wewnątrz Haystack (ConditionalRouter)"""

        routes = [
            {
                "condition": "{{ query|length < 20 }}",
                "output": "{{ query }}",
                "output_name": "short_query",
                "output_type": str,
            },
            {
                "condition": "{{ query|length >= 20 }}",
                "output": "{{ query }}",
                "output_name": "long_query",
                "output_type": str,
            },
        ]

        pipe = Pipeline()
        pipe.add_component("router", ConditionalRouter(routes))

        pipe.add_component(
            "short_llm",
            OpenAIGenerator(
                api_key=self.api_key,
                api_base_url=self.host,
                model=self.default_model,
            ),
        )
        pipe.add_component(
            "long_llm",
            OpenAIGenerator(
                api_key=self.api_key,
                api_base_url=self.host,
                model=self.default_model,
            ),
        )

        pipe.connect("router.short_query", "short_llm.prompt")
        pipe.connect("router.long_query", "long_llm.prompt")

        query = "Co to AI?"
        print(f"Testing Conditional Router with query: '{query}'")

        result = pipe.run({"router": {"query": query}})

        if "short_llm" in result:
            print("Routed to Short LLM:", result["short_llm"]["replies"][0])
        elif "long_llm" in result:
            print("Routed to Long LLM:", result["long_llm"]["replies"][0])

        return result

    # ---------------------------
    # 9. Error Handling Example
    # ---------------------------
    def error_handling_example(self):
        """Obsługa błędów przy nieistniejącym modelu"""

        print("Testing error handling with non-existent model...")
        generator = OpenAIGenerator(
            api_key=self.api_key,
            api_base_url=self.host,
            model="nonexistent-model-xyz",
        )

        try:
            generator.run(prompt="Test")
        except Exception as e:
            print(f"Success! Caught expected error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    print("=" * 80)
    print("Haystack + LLM Router Integration Examples")
    print("=" * 80)

    examples = HaystackExamples()

    print("\n1. Basic Example")
    print("-" * 80)
    examples.basic_example()

    print("\n2. Pipeline Example")
    print("-" * 80)
    examples.pipeline_example()
    #
    print("\n3. Chat Example")
    print("-" * 80)
    examples.chat_example()

    print("\n4. Streaming Example")
    print("-" * 80)
    examples.streaming_example()

    # TODO
    # print("\n5. RAG Pipeline Example")
    # print("-" * 80)
    # examples.rag_pipeline_example()

    print("\n6. Multi-Model Pipeline")
    print("-" * 80)
    examples.multi_model_pipeline()

    print("\n7. Custom Parameters Example")
    print("-" * 80)
    examples.custom_parameters_example()

    print("\n8. Conditional Pipeline")
    print("-" * 80)
    examples.conditional_pipeline()
    #
    print("\n9. Error Handling Example")
    print("-" * 80)
    examples.error_handling_example()

    print("\n" + "=" * 80)
    print("Wszystkie przykłady zakończone!")
    print("=" * 80)
