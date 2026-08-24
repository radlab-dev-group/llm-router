"""
Tests for the generate_article_from_text endpoint and client library components.
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
    GenerateArticleFromTextModel,
    GENERATE_ARTICLE_FROM_TEXT_REQ,
    GENERATE_ARTICLE_FROM_TEXT_OPT,
)
from llm_router_lib.services.utils import GenerateArticleFromTextService
from llm_router_lib.client import LLMRouterClient
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_api.endpoints.builtin.builtin_utils import GenerateArticleFromText
from llm_router_api.core.auth.policies.engine import _ENDPOINT_PERMISSION_MAP


class TestGenerateArticleFromTextDataModel:
    """Tests for GenerateArticleFromTextModel pydantic validation."""

    def test_valid_payload(self):
        model = GenerateArticleFromTextModel(
            model_name="test-model",
            text="Behörden haben eine Sturmflutwarnung herausgegeben.",
            temperature=0.7,
        )
        assert model.model_name == "test-model"
        assert model.text.startswith("Behörden")
        assert model.temperature == 0.7

    def test_missing_model_name_raises(self):
        with pytest.raises(ValidationError):
            GenerateArticleFromTextModel(text="Tekst")

    def test_missing_text_raises(self):
        with pytest.raises(ValidationError):
            GenerateArticleFromTextModel(model_name="test-model")

    def test_constants(self):
        assert "text" in GENERATE_ARTICLE_FROM_TEXT_REQ
        assert "model_name" in GENERATE_ARTICLE_FROM_TEXT_REQ
        assert "temperature" in GENERATE_ARTICLE_FROM_TEXT_OPT
        assert "max_new_tokens" in GENERATE_ARTICLE_FROM_TEXT_OPT


class TestGenerateArticleFromTextEndpoint:
    """Tests for the GenerateArticleFromText endpoint class."""

    @pytest.fixture
    def endpoint(self):
        return GenerateArticleFromText(
            logger_file_name=None,
            prompt_handler=None,
            model_handler=None,
        )

    def test_endpoint_attributes(self, endpoint):
        assert endpoint.name == "generate_article_from_text"
        assert endpoint.method == "POST"
        assert "builtin" in endpoint._ep_types_str
        assert endpoint._call_for_each_user_msg is False
        assert endpoint.SYSTEM_PROMPT_NAME == {
            "pl": "builtin/system/pl/news-on-sm",
            "en": "builtin/system/en/news-on-sm",
        }

    def test_prepare_payload(self, endpoint):
        params = {
            "model_name": "test-model",
            "text": "Sturmtief Detlef zieht über Deutschland.",
        }
        payload = endpoint.prepare_payload(params)
        assert payload is not None
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert payload["messages"] == [
            {
                "role": "user",
                "content": "Sturmtief Detlef zieht über Deutschland.",
            }
        ]

    def test_prepare_response_function(self, endpoint):
        endpoint._start_time = time.time()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Krótka wiadomość."}}]
        }

        result = endpoint._prepare_response_function(mock_response)
        assert "response" in result
        assert "generation_time" in result
        assert result["response"] == {"article_text": "Krótka wiadomość."}


class TestGenerateArticleFromTextServiceAndClient:
    """Tests for GenerateArticleFromTextService and LLMRouterClient."""

    def test_service_attributes(self):
        assert (
            GenerateArticleFromTextService.endpoint
            == "/api/generate_article_from_text"
        )
        assert (
            GenerateArticleFromTextService.model_cls is GenerateArticleFromTextModel
        )

    def test_client_generate_news_from_text_with_model_instance(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            GenerateArticleFromTextService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True, "response": {}}
            payload = GenerateArticleFromTextModel(
                model_name="test-model", text="Tekst źródłowy"
            )
            resp = client.generate_article_from_text(payload=payload)
            assert resp == {"status": True, "response": {}}
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["text"] == "Tekst źródłowy"

    def test_client_generate_news_from_text_with_dict_payload(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            GenerateArticleFromTextService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            payload = {"model_name": "test-model", "text": "Tekst źródłowy"}
            resp = client.generate_article_from_text(payload=payload)
            assert resp == {"status": True}
            mock_call.assert_called_once_with(payload)

    def test_client_generate_news_from_text_with_args(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            GenerateArticleFromTextService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generate_article_from_text(
                text="Tekst źródłowy", model="test-model"
            )
            assert resp == {"status": True}
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["text"] == "Tekst źródłowy"

    def test_client_generate_news_from_text_with_default_model(self):
        client = LLMRouterClient(
            api="http://localhost:8080", default_model="def-model"
        )
        with mock.patch.object(
            GenerateArticleFromTextService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generate_article_from_text(text="Tekst źródłowy")
            assert resp == {"status": True}
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "def-model"

    def test_client_generate_news_from_text_no_args_raises(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with pytest.raises((NoArgsAndNoPayloadError, ValidationError)):
            client.generate_article_from_text()


class TestGenerateArticleFromTextAuthAndPrompts:
    """Tests for auth policy mapping and prompt files."""

    def test_endpoint_permission_map(self):
        assert "post:/api/generate_article_from_text" in _ENDPOINT_PERMISSION_MAP
        assert (
            _ENDPOINT_PERMISSION_MAP["post:/api/generate_article_from_text"]
            == "builtin"
        )

    def test_prompt_files_exist_and_contain_phrases(self):
        pl_prompt_path = "resources/prompts/builtin/system/pl/news-on-sm.prompt"
        en_prompt_path = "resources/prompts/builtin/system/en/news-on-sm.prompt"

        assert os.path.exists(pl_prompt_path)
        assert os.path.exists(en_prompt_path)

        with open(pl_prompt_path, encoding="utf-8") as f:
            pl_content = f.read().lower()
            assert "news" in pl_content

        with open(en_prompt_path, encoding="utf-8") as f:
            en_content = f.read().lower()
            assert "news" in en_content
