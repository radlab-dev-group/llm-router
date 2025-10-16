from llm_router_lib.data_models.builtin_chat import (
    GenerativeConversationModel,
    ExtendedGenerativeConversationModel,
)

from llm_router_lib.tests.base import BaseEndpointTest


class ConversationWithModelTest(BaseEndpointTest):
    payload = {
        "model_name": "google/gemma-3-12b-it",
        "user_last_statement": "Cześć, jak się masz?",
        "historical_messages": [
            {"user": "Witaj"},
            {"assistant": "Witam!"},
        ],
        "temperature": 0.7,
        "max_new_tokens": 128,
    }
    payload_model = GenerativeConversationModel

    def client_method(self):
        return self._client.conversation_with_model


class ExtendedConversationWithModelTest(BaseEndpointTest):
    payload = {
        "sys.argv": "google/gemma-3-12b-it",
        "user_last_statement": "Cześć, jak się masz?",
        "system_prompt": "Odpowiadaj jak mistrz Yoda.",
        "temperature": 0.7,
        "max_new_tokens": 128,
    }
    payload_model = ExtendedGenerativeConversationModel

    def client_method(self):
        return self._client.extended_conversation_with_model
