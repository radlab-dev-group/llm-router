import os

from llm_router_lib import LLMRouterClient
from llm_router_lib.tests.builtin_conversation import (
    ConversationWithModelTest,
    ExtendedConversationWithModelTest,
)


class Models:
    google_gemma_vllm = "google/gemma-3-12b-it"


def prepare_tests(client: LLMRouterClient):
    return [
        [ConversationWithModelTest(client=client), Models.google_gemma_vllm],
        [ExtendedConversationWithModelTest(client=client), Models.google_gemma_vllm],
    ]


def main():
    api_host = os.getenv("LLM_API_HOST", "http://192.168.100.65:8080")
    token = os.getenv("LLM_API_TOKEN", "")

    client = LLMRouterClient(api=api_host, token=token)

    for test, model_name in prepare_tests(client):
        print(test.run(model_name=model_name))


if __name__ == "__main__":
    main()
