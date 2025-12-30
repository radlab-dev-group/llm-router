"""
LangChain Integration Example

Demonstrates how to integrate LangChain with an LLM Router.
Simply change the base_url in the constants module!
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from langchain import hub
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

# from langchain.chains import RetrievalQA
from langchain.agents import create_react_agent, AgentExecutor

from constants import HOST, MODELS


class LangChainExamples:
    """
    Helper class that groups all LangChain‑Router example calls.
    Usage:
        examples = LangChainExamples()
        examples.basic_example()
    """

    def __init__(self, host: str = HOST):
        self.base_url = host

    # ------------ 1. Basic Example ------------
    def basic_example(self):
        """Basic example using LangChain"""
        llm = ChatOpenAI(
            model=MODELS[0],
            base_url=self.base_url,
            api_key="not-needed",
            temperature=0.7,
        )
        messages = [
            SystemMessage(
                content="You are a helpful AI assistant specialized in programming."
            ),
            HumanMessage(content="Explain what an LLM Router is in one sentence."),
        ]
        response = llm.invoke(messages)
        print("Response:", response.content)
        return response

    # ------------ 2. Streaming Example ------------
    def streaming_example(self):
        """Streaming response example"""
        llm = ChatOpenAI(
            model=MODELS[0],
            base_url=self.base_url,
            api_key="not-needed",
        )
        messages = [
            HumanMessage(content="Write a short poem about cloud computing.")
        ]
        print("Streaming response:")
        for chunk in llm.stream(messages):
            print(chunk.content, end="", flush=True)
        print("\n")

    # ------------ 3. Chain (LCEL) Example ------------
    def chain_example(self):
        """LCEL (LangChain Expression Language) example"""
        llm = ChatOpenAI(
            model=MODELS[0],
            base_url=self.base_url,
            api_key="not-needed",
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", "You are an expert on {topic}."),
                ("user", "{question}"),
            ]
        )
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke(
            {
                "topic": "distributed infrastructure",
                "question": "What are the benefits of load balancing?",
            }
        )
        print("Chain response:", response)
        return response

    # ------------ 4. RAG Example ------------
    # def rag_example(self):
    #     """Retrieval‑Augmented Generation example"""
    #     # Documents to index
    #     docs = [
    #         Document(
    #             page_content="LLM Router is an
    #             open‑source gateway for LLM infrastructure."
    #         ),
    #         Document(
    #             page_content="Router handles load
    #             balancing across multiple providers."
    #         ),
    #         Document(
    #             page_content="Supports OpenAI, Ollama, vLLM and other back‑ends."
    #         ),
    #         Document(page_content="Offers streaming,
    #         health checks and monitoring."),
    #     ]
    #
    #     # LLM via router
    #     llm = ChatOpenAI(
    #         model=MODELS[0],
    #         base_url=self.base_url,
    #         api_key="not-needed",
    #     )
    #
    #     # Embeddings (router may expose an embedding endpoint)
    #     embeddings = OpenAIEmbeddings(
    #         base_url=self.base_url,
    #         api_key="not-needed",
    #     )
    #
    #     # Build vector store
    #     vectorstore = FAISS.from_documents(docs, embeddings)
    #
    #     # RetrievalQA chain
    #     qa_chain = RetrievalQA.from_chain_type(
    #         llm=llm,
    #         retriever=vectorstore.as_retriever(),
    #         return_source_documents=True,
    #     )
    #     result = qa_chain.invoke({"query": "What is an LLM Router?"})
    #     print("RAG Answer:", result["result"])
    #     print("Sources:", [doc.page_content for doc in result["source_documents"]])
    #     return result

    # ------------ 5. Batch Processing Example ------------
    def batch_example(self):
        """Batch processing example"""
        llm = ChatOpenAI(
            model=MODELS[0],
            base_url=self.base_url,
            api_key="not-needed",
        )
        messages_batch = [
            [HumanMessage(content="What is Python?")],
            [HumanMessage(content="What is Docker?")],
            [HumanMessage(content="What is Kubernetes?")],
        ]
        print("Batch processing:")
        responses = llm.batch(messages_batch)
        for i, response in enumerate(responses, 1):
            print(f"{i}. {response.content}\n")
        return responses

    # ------------ 6. Multi‑Model Example ------------
    def multi_model_example(self):
        """Query multiple models via the router"""
        llm_gemma = ChatOpenAI(
            model=MODELS[0],
            base_url=self.base_url,
            api_key="not-needed",
        )
        llm_gpt = ChatOpenAI(
            model=MODELS[1],
            base_url=self.base_url,
            api_key="not-needed",
        )
        question = [HumanMessage(content="List three advantages of load balancing.")]

        print("Gemma response:")
        response1 = llm_gemma.invoke(question)
        print(response1.content)

        print("\nGPT‑OSS response:")
        response2 = llm_gpt.invoke(question)
        print(response2.content)

    # ------------ 7. Agent Example ------------
    def agent_example(self):
        """LangChain Agent example using ReAct strategy"""

        # 1. Definicja narzędzia
        @tool
        def get_router_status(query: str) -> str:
            """
            Returns the status of the LLM Router.
            Use this for any questions regarding router status.
            """
            # Model czasem przekazuje tu zbędne argumenty, więc warto,
            # by funkcja przyjmowała stringa, nawet jeśli go nie używa.
            return "LLM Router is operational and serving 3 models."

        # 2. Konfiguracja LLM
        llm = ChatOpenAI(
            model=MODELS[0],
            base_url=self.base_url,
            api_key="not-needed",
            temperature=0,  # Ważne: 0 zmniejsza "halucynacje" przy używaniu narzędzi
        )

        tools = [get_router_status]

        # 3. Pobranie promptu ReAct
        # To pobiera standardowy szablon:
        # "Answer the following questions as best you can..."
        # Wymaga: pip install langchainhub
        prompt = hub.pull("hwchase17/react")

        # 4. Tworzenie Agenta typu ReAct
        # Ten typ agenta "myśli" tekstem (Thought -> Action -> Observation),
        # co działa na prawie każdym modelu LLM.
        agent = create_react_agent(llm, tools, prompt)

        # 5. Egzekutor
        # handle_parsing_errors=True jest kluczowe dla modeli lokalnych,
        # które czasem zwracają poprawną odpowiedź, ale w nieco krzywym formacie.
        agent_executor = AgentExecutor(
            agent=agent, tools=tools, verbose=True, handle_parsing_errors=True
        )

        print(f"Uruchamiam agenta z modelem: {MODELS[0]}...")

        # 6. Uruchomienie
        # Input musi być jasny, aby wymusić użycie narzędzia
        result = agent_executor.invoke(
            {"input": "What is the router status? Check it now."}
        )

        print("Agent response:", result["output"])
        return result

    # ------------ 8. Error Handling Example ------------
    def error_handling_example(self):
        """Error handling example"""
        llm = ChatOpenAI(
            model="nonexistent-model",
            base_url=self.base_url,
            api_key="not-needed",
        )
        try:
            response = llm.invoke([HumanMessage(content="Test")])
            print(response.content)
        except Exception as e:
            print(f"Error caught: {type(e).__name__}: {e}")
            print(
                "Router returned an error – model does not exist in the configuration."
            )


if __name__ == "__main__":
    print("=" * 80)
    print("LangChain + LLM Router Integration Examples")
    print("=" * 80)

    examples = LangChainExamples()

    print("\n1. Basic Example")
    print("-" * 80)
    examples.basic_example()

    print("\n2. Streaming Example")
    print("-" * 80)
    examples.streaming_example()

    print("\n3. Chain Example (LCEL)")
    print("-" * 80)
    examples.chain_example()

    # TODO: CHECK!!!!!
    # print("\n4. RAG Example")
    # print("-" * 80)
    # examples.rag_example()

    print("\n5. Batch Processing Example")
    print("-" * 80)
    examples.batch_example()
    #
    print("\n6. Multi‑Model Example")
    print("-" * 80)
    examples.multi_model_example()

    print("\n7. Agent Example")
    print("-" * 80)
    examples.agent_example()

    print("\n8. Error Handling Example")
    print("-" * 80)
    examples.error_handling_example()

    print("\n" + "=" * 80)
    print("All examples completed!")
    print("=" * 80)
