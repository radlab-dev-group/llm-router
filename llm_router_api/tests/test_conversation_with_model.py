"""
Tests for the conversation_with_model and extended_conversation_with_model
endpoints and client library components.
"""

from __future__ import annotations

import os
import time

import pytest
from unittest import mock
from pydantic import ValidationError

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from llm_router_lib.data_models.builtin_chat import (
    ConversationWithModelRequest,
    ExtendedConversationWithModelRequest,
    GENAI_CONV_REQ_ARGS,
    GENAI_CONV_OPT_ARGS,
    EXT_GENAI_CONV_REQ_ARGS,
    EXT_GENAI_CONV_OPT_ARGS,
)
from llm_router_lib.services.conversation import (
    ConversationWithModelService,
    ExtendedConversationWithModelService,
)
from llm_router_lib.client import LLMRouterClient
from llm_router_api.endpoints.builtin.builtin_chat import (
    ConversationWithModel,
    ExtendedConversationWithModel,
)
from llm_router_api.core.auth.policies.engine import _ENDPOINT_PERMISSION_MAP


class TestConversationWithModelDataModel:
    """Tests for ConversationWithModelRequest pydantic validation."""

    def test_valid_payload(self):
        model = ConversationWithModelRequest(
            model_name="test-model",
            user_last_statement="Cześć, jak się masz?",
            historical_messages=[
                {"user": "Witaj"},
                {"assistant": "Witam!"},
            ],
            temperature=0.7,
        )
        assert model.model_name == "test-model"
        assert model.user_last_statement == "Cześć, jak się masz?"
        assert len(model.historical_messages) == 2
        assert model.temperature == 0.7

    def test_historical_messages_default_empty(self):
        model = ConversationWithModelRequest(
            model_name="test-model",
            user_last_statement="Cześć",
        )
        assert model.historical_messages == []

    def test_missing_model_name_raises(self):
        with pytest.raises(ValidationError):
            ConversationWithModelRequest(user_last_statement="Cześć")

    def test_missing_user_last_statement_raises(self):
        with pytest.raises(ValidationError):
            ConversationWithModelRequest(model_name="test-model")

    def test_constants(self):
        assert "user_last_statement" in GENAI_CONV_REQ_ARGS
        assert "model_name" in GENAI_CONV_REQ_ARGS
        assert "historical_messages" in GENAI_CONV_OPT_ARGS
        assert "temperature" in GENAI_CONV_OPT_ARGS


class TestExtendedConversationWithModelDataModel:
    """Tests for ExtendedConversationWithModelRequest pydantic validation."""

    def test_valid_payload(self):
        model = ExtendedConversationWithModelRequest(
            model_name="test-model",
            user_last_statement="Cześć",
            system_prompt="Odpowiadaj jak mistrz Yoda.",
        )
        assert model.system_prompt == "Odpowiadaj jak mistrz Yoda."

    def test_missing_system_prompt_raises(self):
        with pytest.raises(ValidationError):
            ExtendedConversationWithModelRequest(
                model_name="test-model", user_last_statement="Cześć"
            )

    def test_constants(self):
        assert "system_prompt" in EXT_GENAI_CONV_REQ_ARGS
        assert "user_last_statement" in EXT_GENAI_CONV_REQ_ARGS


class TestConversationWithModelEndpoint:
    """Tests for the ConversationWithModel endpoint class."""

    @pytest.fixture
    def endpoint(self):
        return ConversationWithModel(
            logger_file_name=None,
            prompt_handler=None,
            model_handler=None,
        )

    def test_endpoint_attributes(self, endpoint):
        assert endpoint.name == "conversation_with_model"
        assert endpoint.method == "POST"
        assert "builtin" in endpoint._ep_types_str
        assert endpoint.SYSTEM_PROMPT_NAME == {
            "pl": "builtin/system/pl/chat-conversation-simple",
            "en": "builtin/system/en/chat-conversation-simple",
        }

    def test_prepare_payload(self, endpoint):
        params = {
            "model_name": "test-model",
            "user_last_statement": "Jaka jest kategoria tekstu?",
            "historical_messages": [
                {"user": "Witaj"},
                {"assistant": "Witam!"},
            ],
        }
        payload = endpoint.prepare_payload(params)
        assert payload is not None
        assert payload["model"] == "test-model"
        assert "historical_messages" not in payload
        assert payload["messages"] == [
            {"role": "user", "content": "Witaj"},
            {"role": "assistant", "content": "Witam!"},
            {
                "role": "user",
                "content": "Jaka jest kategoria tekstu?",
            },
        ]

    def test_prepare_payload_without_history(self, endpoint):
        params = {
            "model_name": "test-model",
            "user_last_statement": "Cześć",
        }
        payload = endpoint.prepare_payload(params)
        assert payload["messages"] == [{"role": "user", "content": "Cześć"}]

    def test_prepare_response_function(self, endpoint):
        endpoint._start_time = time.time()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Kategoria: zwierzęta"}}]
        }

        result = endpoint._prepare_response_function(mock_response)
        assert "response" in result
        assert "generation_time" in result
        assert result["response"] == "Kategoria: zwierzęta"


class TestExtendedConversationWithModelEndpoint:
    """Tests for the ExtendedConversationWithModel endpoint class."""

    @pytest.fixture
    def endpoint(self):
        return ExtendedConversationWithModel(
            logger_file_name=None,
            prompt_handler=None,
            model_handler=None,
        )

    def test_endpoint_attributes(self, endpoint):
        assert endpoint.name == "extended_conversation_with_model"
        assert endpoint.method == "POST"
        assert "builtin" in endpoint._ep_types_str
        assert endpoint.SYSTEM_PROMPT_NAME is None

    def test_prepare_payload_includes_system_prompt(self, endpoint):
        params = {
            "model_name": "test-model",
            "user_last_statement": "Cześć",
            "system_prompt": "Odpowiadaj jak mistrz Yoda.",
        }
        payload = endpoint.prepare_payload(params)
        assert payload is not None
        assert payload["model"] == "test-model"
        assert payload["messages"][0] == {
            "role": "system",
            "content": "Odpowiadaj jak mistrz Yoda.",
        }
        assert payload["messages"][1] == {
            "role": "user",
            "content": "Cześć",
        }

    def test_prepare_response_function(self, endpoint):
        endpoint._start_time = time.time()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Cześć mój uczniu."}}]
        }

        result = endpoint._prepare_response_function(mock_response)
        assert result["response"] == "Cześć mój uczniu."


class TestConversationServiceAndClient:
    """Tests for ConversationWithModelService and LLMRouterClient."""

    def test_conversation_service_attributes(self):
        assert (
            ConversationWithModelService.endpoint == "/api/conversation_with_model"
        )
        assert ConversationWithModelService.model_cls is ConversationWithModelRequest

    def test_extended_conversation_service_attributes(self):
        assert (
            ExtendedConversationWithModelService.endpoint
            == "/api/extended_conversation_with_model"
        )
        assert (
            ExtendedConversationWithModelService.model_cls
            is ExtendedConversationWithModelRequest
        )

    def test_client_conversation_with_model_with_model_instance(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            ConversationWithModelService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True, "response": "Odpowiedź"}
            payload = ConversationWithModelRequest(
                model_name="test-model", user_last_statement="Cześć"
            )
            resp = client.conversation_with_model(payload=payload)
            assert resp == {"status": True, "response": "Odpowiedź"}
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["user_last_statement"] == "Cześć"

    def test_client_conversation_with_model_with_dict_payload(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            ConversationWithModelService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            payload = {
                "model_name": "test-model",
                "user_last_statement": "Cześć",
            }
            resp = client.conversation_with_model(payload=payload)
            assert resp == {"status": True}
            mock_call.assert_called_once_with(payload)

    def test_client_conversation_with_model_no_payload_raises(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with pytest.raises(TypeError):
            client.conversation_with_model()

    def test_client_extended_conversation_with_model_with_model_instance(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            ExtendedConversationWithModelService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True, "response": "Odpowiedź"}
            payload = ExtendedConversationWithModelRequest(
                model_name="test-model",
                user_last_statement="Cześć",
                system_prompt="Jak Yoda",
            )
            resp = client.extended_conversation_with_model(payload=payload)
            assert resp == {"status": True, "response": "Odpowiedź"}
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["system_prompt"] == "Jak Yoda"

    def test_client_extended_conversation_with_model_with_dict_payload(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            ExtendedConversationWithModelService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            payload = {
                "model_name": "test-model",
                "user_last_statement": "Cześć",
                "system_prompt": "Jak Yoda",
            }
            resp = client.extended_conversation_with_model(payload=payload)
            assert resp == {"status": True}
            mock_call.assert_called_once_with(payload)

    def test_client_extended_conversation_with_model_no_payload_raises(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with pytest.raises(TypeError):
            client.extended_conversation_with_model()


class TestConversationAuthAndPrompts:
    """Tests for auth policy mapping and prompt files."""

    def test_endpoint_permission_map(self):
        assert "post:/api/conversation_with_model" in _ENDPOINT_PERMISSION_MAP
        assert (
            _ENDPOINT_PERMISSION_MAP["post:/api/conversation_with_model"]
            == "builtin"
        )
        assert (
            "post:/api/extended_conversation_with_model" in _ENDPOINT_PERMISSION_MAP
        )
        assert (
            _ENDPOINT_PERMISSION_MAP["post:/api/extended_conversation_with_model"]
            == "builtin"
        )

    def test_prompt_files_exist_and_contain_phrases(self):
        pl_prompt_path = (
            "resources/prompts/builtin/system/pl/chat-conversation-simple.prompt"
        )
        en_prompt_path = (
            "resources/prompts/builtin/system/en/chat-conversation-simple.prompt"
        )

        assert os.path.exists(pl_prompt_path)
        assert os.path.exists(en_prompt_path)

        with open(pl_prompt_path, encoding="utf-8") as f:
            pl_content = f.read().lower()
            assert "czacie" in pl_content

        with open(en_prompt_path, encoding="utf-8") as f:
            en_content = f.read().lower()
            assert "chat" in en_content
