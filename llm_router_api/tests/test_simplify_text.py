"""
Tests for the simplify_text endpoint and client library components.
"""

from __future__ import annotations

import os
import time

import pytest
from unittest import mock
from pydantic import ValidationError

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from llm_router_lib.data_models.builtin_utils import (
    SimplifyTextModel,
    SIMPLIFY_TEXT_REQ,
    SIMPLIFY_TEXT_OPT,
)
from llm_router_lib.services.utils import SimplifyTextService
from llm_router_lib.client import LLMRouterClient
from llm_router_lib.data_models.response import SimplifyTextResponse
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_api.endpoints.builtin.builtin_utils import SimplifyText
from llm_router_api.core.auth.policies.engine import _ENDPOINT_PERMISSION_MAP


class TestSimplifyTextDataModel:
    """Tests for SimplifyTextModel pydantic validation."""

    def test_valid_payload(self):
        model = SimplifyTextModel(
            model_name="test-model",
            texts=["Zgodnie z postanowieniami rozporządzenia ministerialnego."],
            temperature=0.2,
        )
        assert model.model_name == "test-model"
        assert len(model.texts) == 1
        assert model.temperature == 0.2

    def test_missing_model_name_raises(self):
        with pytest.raises(ValidationError):
            SimplifyTextModel(texts=["Tekst"])

    def test_missing_texts_raises(self):
        with pytest.raises(ValidationError):
            SimplifyTextModel(model_name="test-model")

    def test_constants(self):
        assert "texts" in SIMPLIFY_TEXT_REQ
        assert "model_name" in SIMPLIFY_TEXT_REQ
        assert "temperature" in SIMPLIFY_TEXT_OPT
        assert "language" in SIMPLIFY_TEXT_OPT


class TestSimplifyTextEndpoint:
    """Tests for the SimplifyText endpoint class."""

    @pytest.fixture
    def endpoint(self):
        return SimplifyText(
            logger_file_name=None,
            prompt_handler=None,
            model_handler=None,
        )

    def test_endpoint_attributes(self, endpoint):
        assert endpoint.name == "simplify_text"
        assert endpoint.method == "POST"
        assert "builtin" in endpoint._ep_types_str
        assert endpoint._call_for_each_user_msg is True
        assert endpoint.SYSTEM_PROMPT_NAME == {
            "pl": "builtin/system/pl/simplify-text",
            "en": "builtin/system/en/simplify-text",
        }

    def test_prepare_payload(self, endpoint):
        params = {
            "model_name": "test-model",
            "texts": ["Tekst formalny 1", "Tekst formalny 2"],
        }
        payload = endpoint.prepare_payload(params)
        assert payload is not None
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert "texts" not in payload
        assert payload["messages"] == [
            {"role": "user", "content": "Tekst formalny 1"},
            {"role": "user", "content": "Tekst formalny 2"},
        ]

    def test_prepare_response_function(self, endpoint):
        endpoint._start_time = time.time()

        mock_response_1 = mock.MagicMock()
        mock_response_1.json.return_value = {
            "choices": [{"message": {"content": "Prosty tekst 1"}}]
        }
        mock_response_2 = mock.MagicMock()
        mock_response_2.json.return_value = {
            "choices": [{"message": {"content": "Prosty tekst 2"}}]
        }

        responses = [mock_response_1, mock_response_2]
        contents = ["Tekst formalny 1", "Tekst formalny 2"]

        result = endpoint._prepare_response_function(responses, contents)
        assert "response" in result
        assert "generation_time" in result
        assert result["response"] == ["Prosty tekst 1", "Prosty tekst 2"]


class TestSimplifyTextServiceAndClient:
    """Tests for SimplifyTextService and LLMRouterClient.simplify_text."""

    def test_service_attributes(self):
        assert SimplifyTextService.endpoint == "/api/simplify_text"
        assert SimplifyTextService.model_cls == SimplifyTextModel

    def test_client_simplify_texts_with_model_instance(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(SimplifyTextService, "call_post") as mock_call:
            mock_call.return_value = {"status": True, "response": []}
            payload = SimplifyTextModel(model_name="test-model", texts=["Formalny"])
            resp = client.simplify_text(payload=payload)
            assert isinstance(resp, SimplifyTextResponse)
            assert resp.response == []
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["texts"] == ["Formalny"]

    def test_client_simplify_texts_with_dict_payload_raises_type_error(self):
        client = LLMRouterClient(api="http://localhost:8080")
        payload = {"model_name": "test-model", "texts": ["Formalny"]}
        with pytest.raises(TypeError):
            client.simplify_text(payload=payload)

    def test_client_simplify_texts_with_args(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(SimplifyTextService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.simplify_text(
                texts=["Formalny 1", "Formalny 2"],
                model="test-model",
                temperature=0.1,
            )
            assert isinstance(resp, SimplifyTextResponse)
            assert resp.response == []
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["texts"] == ["Formalny 1", "Formalny 2"]
            assert call_arg["temperature"] == 0.1

    def test_client_simplify_texts_with_default_model(self):
        client = LLMRouterClient(
            api="http://localhost:8080", default_model="def-model"
        )
        with mock.patch.object(SimplifyTextService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.simplify_text(texts=["Formalny"])
            assert isinstance(resp, SimplifyTextResponse)
            assert resp.response == []
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "def-model"

    def test_client_simplify_texts_no_args_raises(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with pytest.raises((NoArgsAndNoPayloadError, ValidationError)):
            client.simplify_text()


class TestSimplifyTextAuthAndPrompts:
    """Tests for auth policy mapping and prompt files."""

    def test_endpoint_permission_map(self):
        assert "post:/api/simplify_text" in _ENDPOINT_PERMISSION_MAP
        assert _ENDPOINT_PERMISSION_MAP["post:/api/simplify_text"] == "builtin"

    def test_prompt_files_exist_and_contain_phrases(self):
        pl_prompt_path = "resources/prompts/builtin/system/pl/simplify-text.prompt"
        en_prompt_path = "resources/prompts/builtin/system/en/simplify-text.prompt"

        assert os.path.exists(pl_prompt_path)
        assert os.path.exists(en_prompt_path)

        with open(pl_prompt_path, encoding="utf-8") as f:
            pl_content = f.read().lower()
            assert "upraszczać" in pl_content

        with open(en_prompt_path, encoding="utf-8") as f:
            en_content = f.read().lower()
            assert "simplify" in en_content
