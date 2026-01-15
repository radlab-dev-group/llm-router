import os
import json

from llm_router_lib import LLMRouterClient
from llm_router_lib.tests.builtin_conversation import (
    ConversationWithModelTest,
    ExtendedConversationWithModelTest,
    AnswerBasedOnTheContextModelTest,
)
from llm_router_lib.tests.builtin_ping import PingTest
from llm_router_lib.tests.builtin_utils import TranslateTextModelTest


class Models:
    google_gemma_vllm = "google/gemma-3-12b-it"
    speakleash_bielik_2_3 = "speakleash/Bielik-11B-v2.3-Instruct"


def prepare_tests(client: LLMRouterClient):
    return [
        # [ConversationWithModelTest(client=client), Models.google_gemma_vllm],
        # [ExtendedConversationWithModelTest(client=client), Models.google_gemma_vllm],
        # [AnswerBasedOnTheContextModelTest(client=client), Models.google_gemma_vllm],
        [TranslateTextModelTest(client=client), Models.speakleash_bielik_2_3],
        # [PingTest(client=client), None],
    ]


def main():
    api_host = os.getenv("LLM_API_HOST", "http://192.168.100.65:8080")
    token = os.getenv("LLM_API_TOKEN", "")

    client = LLMRouterClient(api=api_host, token=token, timeout=180)

    for test, model_name in prepare_tests(client):
        print(
            json.dumps(test.run(model_name=model_name), indent=1, ensure_ascii=False)
        )


if __name__ == "__main__":
    main()
