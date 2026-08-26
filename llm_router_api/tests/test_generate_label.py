"""
Tests for the generate_label endpoint and client library components.
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
    GenerateLabelModel,
    GENERATE_LABEL_REQ,
    GENERATE_LABEL_OPT,
)
from llm_router_lib.services.utils import GenerateLabelService
from llm_router_lib.client import LLMRouterClient
from llm_router_lib.data_models.response import GenerateLabelResponse
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_api.endpoints.builtin.builtin_utils import GenerateLabel
from llm_router_api.core.auth.policies.engine import _ENDPOINT_PERMISSION_MAP


class TestGenerateLabelDataModel:
    """Tests for GenerateLabelModel pydantic validation."""

    def test_valid_payload(self):
        model = GenerateLabelModel(
            model_name="test-model",
            texts=["Smartfony z większą baterią", "Premiera nowych aparatów"],
            temperature=0.2,
        )
        assert model.model_name == "test-model"
        assert len(model.texts) == 2
        assert model.temperature == 0.2

    def test_missing_model_name_raises(self):
        with pytest.raises(ValidationError):
            GenerateLabelModel(texts=["Tekst"])

    def test_missing_texts_raises(self):
        with pytest.raises(ValidationError):
            GenerateLabelModel(model_name="test-model")

    def test_constants(self):
        assert "texts" in GENERATE_LABEL_REQ
        assert "model_name" in GENERATE_LABEL_REQ
        assert "temperature" in GENERATE_LABEL_OPT


class TestGenerateLabelEndpoint:
    """Tests for the GenerateLabel endpoint class."""

    @pytest.fixture
    def endpoint(self):
        return GenerateLabel(
            logger_file_name=None,
            prompt_handler=None,
            model_handler=None,
        )

    def test_endpoint_attributes(self, endpoint):
        assert endpoint.name == "generate_label"
        assert endpoint.method == "POST"
        assert "builtin" in endpoint._ep_types_str
        assert endpoint._call_for_each_user_msg is False
        assert endpoint.SYSTEM_PROMPT_NAME == {
            "pl": "builtin/system/pl/generate-label",
            "en": "builtin/system/en/generate-label",
        }

    def test_prepare_payload_joins_texts_into_one_message(self, endpoint):
        params = {
            "model_name": "test-model",
            "texts": ["Tekst pierwszy", "Tekst drugi"],
        }
        payload = endpoint.prepare_payload(params)
        assert payload is not None
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert "texts" not in payload
        assert payload["messages"] == [
            {"role": "user", "content": "Tekst pierwszy\n\nTekst drugi"}
        ]

    def test_clean_label_strips_quotes_and_punctuation(self, endpoint):
        assert GenerateLabel._clean_label("  Technologia  ") == "Technologia"
        assert GenerateLabel._clean_label('"Technologia"') == "Technologia"
        assert GenerateLabel._clean_label("'Technologia'") == "Technologia"
        assert GenerateLabel._clean_label("Technologia.") == "Technologia"
        assert GenerateLabel._clean_label("“Technologia”.") == "Technologia"
        assert GenerateLabel._clean_label(None) == ""

    def test_prepare_response_function(self, endpoint):
        endpoint._start_time = time.time()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '"Technologia".'}}]
        }

        result = endpoint._prepare_response_function(mock_response)
        assert "response" in result
        assert "generation_time" in result
        assert result["response"] == "Technologia"


class TestGenerateLabelServiceAndClient:
    """Tests for GenerateLabelService and LLMRouterClient.generate_label."""

    def test_service_attributes(self):
        assert GenerateLabelService.endpoint == "/api/generate_label"
        assert GenerateLabelService.model_cls == GenerateLabelModel

    def test_client_generate_label_with_model_instance(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(GenerateLabelService, "call_post") as mock_call:
            mock_call.return_value = {"status": True, "response": "Technologia"}
            payload = GenerateLabelModel(
                model_name="test-model", texts=["Smartfony"]
            )
            resp = client.generate_label(payload=payload)
            assert isinstance(resp, GenerateLabelResponse)
            assert resp.response == "Technologia"
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["texts"] == ["Smartfony"]

    def test_client_generate_label_with_dict_payload(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(GenerateLabelService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            payload = {"model_name": "test-model", "texts": ["Smartfony"]}
            resp = client.generate_label(payload=payload)
            assert isinstance(resp, GenerateLabelResponse)
            assert resp.response is None
            mock_call.assert_called_once_with(payload)

    def test_client_generate_label_with_args(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(GenerateLabelService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generate_label(
                texts=["Smartfony", "Aparaty"],
                model="test-model",
                temperature=0.1,
            )
            assert isinstance(resp, GenerateLabelResponse)
            assert resp.response is None
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["texts"] == ["Smartfony", "Aparaty"]
            assert call_arg["temperature"] == 0.1

    def test_client_generate_label_with_default_model(self):
        client = LLMRouterClient(
            api="http://localhost:8080", default_model="def-model"
        )
        with mock.patch.object(GenerateLabelService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generate_label(texts=["Smartfony"])
            assert isinstance(resp, GenerateLabelResponse)
            assert resp.response is None
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "def-model"

    def test_client_generate_label_no_args_raises(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with pytest.raises((NoArgsAndNoPayloadError, ValidationError)):
            client.generate_label()


class TestGenerateLabelAuthAndPrompts:
    """Tests for auth policy mapping and prompt files."""

    def test_endpoint_permission_map(self):
        assert "post:/api/generate_label" in _ENDPOINT_PERMISSION_MAP
        assert _ENDPOINT_PERMISSION_MAP["post:/api/generate_label"] == "builtin"

    def test_prompt_files_exist_and_contain_phrases(self):
        pl_prompt_path = "resources/prompts/builtin/system/pl/generate-label.prompt"
        en_prompt_path = "resources/prompts/builtin/system/en/generate-label.prompt"

        assert os.path.exists(pl_prompt_path)
        assert os.path.exists(en_prompt_path)

        with open(pl_prompt_path, encoding="utf-8") as f:
            pl_content = f.read().lower()
            assert "kategorii" in pl_content

        with open(en_prompt_path, encoding="utf-8") as f:
            en_content = f.read().lower()
            assert "category name" in en_content
