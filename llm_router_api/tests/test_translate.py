"""
Tests for the translate endpoint and client library components.
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
    TranslateModel,
    TRANSLATE_TEXT_REQ,
    TRANSLATE_TEXT_OPT,
)
from llm_router_lib.services.utils import TranslateService
from llm_router_lib.client import LLMRouterClient
from llm_router_lib.data_models.response import TranslateResponse
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_api.endpoints.builtin.builtin_utils import Translate
from llm_router_api.core.auth.policies.engine import _ENDPOINT_PERMISSION_MAP


class TestTranslateDataModel:
    """Tests for TranslateModel pydantic validation."""

    def test_valid_payload(self):
        model = TranslateModel(
            model_name="test-model",
            texts=["Hello world", "How are you?"],
            temperature=0.2,
        )
        assert model.model_name == "test-model"
        assert model.texts == ["Hello world", "How are you?"]
        assert model.temperature == 0.2

    def test_missing_model_name_raises(self):
        with pytest.raises(ValidationError):
            TranslateModel(texts=["Hello"])

    def test_missing_texts_raises(self):
        with pytest.raises(ValidationError):
            TranslateModel(model_name="test-model")

    def test_constants(self):
        assert "texts" in TRANSLATE_TEXT_REQ
        assert "model_name" in TRANSLATE_TEXT_REQ
        assert "temperature" in TRANSLATE_TEXT_OPT
        assert "language" in TRANSLATE_TEXT_OPT


class TestTranslateEndpoint:
    """Tests for the Translate endpoint class."""

    @pytest.fixture
    def endpoint(self):
        return Translate(
            logger_file_name=None,
            prompt_handler=None,
            model_handler=None,
        )

    def test_endpoint_attributes(self, endpoint):
        assert endpoint.name == "translate"
        assert endpoint.method == "POST"
        assert "builtin" in endpoint._ep_types_str
        assert endpoint._call_for_each_user_msg is True
        assert endpoint.SYSTEM_PROMPT_NAME == {
            "pl": "builtin/system/pl/translate-to-pl",
            "en": "builtin/system/en/translate-to-pl",
        }

    def test_prepare_payload(self, endpoint):
        params = {
            "model_name": "test-model",
            "texts": ["Hello world", "Good bye"],
        }
        payload = endpoint.prepare_payload(params)
        assert payload is not None
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert "texts" not in payload
        assert payload["messages"] == [
            {"role": "user", "content": "Hello world"},
            {"role": "user", "content": "Good bye"},
        ]

    def test_prepare_response_function(self, endpoint):
        endpoint._start_time = time.time()

        mock_response_1 = mock.MagicMock()
        mock_response_1.json.return_value = {
            "choices": [{"message": {"content": "Witaj świecie"}}]
        }
        mock_response_2 = mock.MagicMock()
        mock_response_2.json.return_value = {
            "choices": [{"message": {"content": "Do widzenia"}}]
        }

        responses = [mock_response_1, mock_response_2]
        contents = ["Hello world", "Good bye"]

        result = endpoint._prepare_response_function(responses, contents)
        assert "response" in result
        assert "generation_time" in result
        assert result["response"] == [
            {"original": "Hello world", "translated": "Witaj świecie"},
            {"original": "Good bye", "translated": "Do widzenia"},
        ]


class TestTranslateServiceAndClient:
    """Tests for TranslateService and LLMRouterClient.translate."""

    def test_service_attributes(self):
        assert TranslateService.endpoint == "/api/translate"
        assert TranslateService.model_cls == TranslateModel

    def test_client_translate_with_model_instance(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(TranslateService, "call_post") as mock_call:
            mock_call.return_value = {"status": True, "response": []}
            payload = TranslateModel(model_name="test-model", texts=["Hi"])
            resp = client.translate(payload=payload)
            assert isinstance(resp, TranslateResponse)
            assert resp.response == []
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["texts"] == ["Hi"]

    def test_client_translate_with_dict_payload_raises_type_error(self):
        client = LLMRouterClient(api="http://localhost:8080")
        payload = {"model_name": "test-model", "texts": ["Hi"]}
        with pytest.raises(TypeError):
            client.translate(payload=payload)

    def test_client_translate_with_args(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(TranslateService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.translate(
                texts=["Hello", "World"], model="test-model", temperature=0.1
            )
            assert isinstance(resp, TranslateResponse)
            assert resp.response == []
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["texts"] == ["Hello", "World"]
            assert call_arg["temperature"] == 0.1

    def test_client_translate_with_default_model(self):
        client = LLMRouterClient(
            api="http://localhost:8080", default_model="def-model"
        )
        with mock.patch.object(TranslateService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.translate(texts=["Hello"])
            assert isinstance(resp, TranslateResponse)
            assert resp.response == []
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "def-model"

    def test_client_translate_no_args_raises(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with pytest.raises((NoArgsAndNoPayloadError, ValidationError)):
            client.translate()


class TestTranslateAuthAndPrompts:
    """Tests for auth policy mapping and prompt files."""

    def test_endpoint_permission_map(self):
        assert "post:/api/translate" in _ENDPOINT_PERMISSION_MAP
        assert _ENDPOINT_PERMISSION_MAP["post:/api/translate"] == "builtin"

    def test_prompt_files_exist_and_contain_phrases(self):
        pl_prompt_path = "resources/prompts/builtin/system/pl/translate-to-pl.prompt"
        en_prompt_path = "resources/prompts/builtin/system/en/translate-to-pl.prompt"

        assert os.path.exists(pl_prompt_path)
        assert os.path.exists(en_prompt_path)

        with open(pl_prompt_path, encoding="utf-8") as f:
            pl_content = f.read().lower()
            assert "tłumacz" in pl_content

        with open(en_prompt_path, encoding="utf-8") as f:
            en_content = f.read().lower()
            assert "translate" in en_content
