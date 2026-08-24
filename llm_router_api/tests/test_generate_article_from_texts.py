"""
Tests for the generate_article_from_texts endpoint and client library components.
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
    GenerateArticleFromTextsModel,
    GENERATE_ARTICLE_FROM_TEXTS_REQ,
    GENERATE_ARTICLE_FROM_TEXTS_OPT,
)
from llm_router_lib.services.utils import GenerateArticleFromTextsService
from llm_router_lib.client import LLMRouterClient
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_api.endpoints.builtin.builtin_utils import (
    GenerateArticleFromTexts,
)
from llm_router_api.core.auth.policies.engine import _ENDPOINT_PERMISSION_MAP


class TestGenerateArticleFromTextsDataModel:
    """Tests for GenerateArticleFromTextsModel pydantic validation."""

    def test_valid_payload(self):
        model = GenerateArticleFromTextsModel(
            model_name="test-model",
            texts=["Tekst 1", "Tekst 2"],
            temperature=0.7,
        )
        assert model.model_name == "test-model"
        assert model.texts == ["Tekst 1", "Tekst 2"]
        assert model.temperature == 0.7

    def test_missing_model_name_raises(self):
        with pytest.raises(ValidationError):
            GenerateArticleFromTextsModel(texts=["Tekst"])

    def test_missing_texts_raises(self):
        with pytest.raises(ValidationError):
            GenerateArticleFromTextsModel(model_name="test-model")

    def test_constants(self):
        assert "texts" in GENERATE_ARTICLE_FROM_TEXTS_REQ
        assert "model_name" in GENERATE_ARTICLE_FROM_TEXTS_REQ
        assert "temperature" in GENERATE_ARTICLE_FROM_TEXTS_OPT


class TestGenerateArticleFromTextsEndpoint:
    """Tests for the GenerateArticleFromTexts endpoint class."""

    @pytest.fixture
    def endpoint(self):
        return GenerateArticleFromTexts(
            logger_file_name=None,
            prompt_handler=None,
            model_handler=None,
        )

    def test_endpoint_attributes(self, endpoint):
        assert endpoint.name == "generate_article_from_texts"
        assert endpoint.method == "POST"
        assert "builtin" in endpoint._ep_types_str
        assert endpoint.SYSTEM_PROMPT_NAME == {
            "pl": "builtin/system/pl/article-from-texts",
            "en": "builtin/system/en/article-from-texts",
        }

    def test_prepare_payload_joins_texts(self, endpoint):
        params = {
            "model_name": "test-model",
            "texts": ["Wydanie 1", "Wydanie 2"],
        }
        payload = endpoint.prepare_payload(params)
        assert payload is not None
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert "texts" not in payload
        assert payload["messages"] == [
            {"role": "user", "content": "Wydanie 1\n\nWydanie 2"}
        ]

    def test_prepare_response_function(self, endpoint):
        endpoint._start_time = time.time()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Artykuł A4."}}]
        }

        result = endpoint._prepare_response_function(mock_response)
        assert "response" in result
        assert "generation_time" in result
        assert result["response"] == {"article_text": "Artykuł A4."}


class TestGenerateArticleFromTextsServiceAndClient:
    """Tests for GenerateArticleFromTextsService and LLMRouterClient."""

    def test_service_attributes(self):
        assert (
            GenerateArticleFromTextsService.endpoint
            == "/api/generate_article_from_texts"
        )
        assert (
            GenerateArticleFromTextsService.model_cls
            is GenerateArticleFromTextsModel
        )

    def test_client_generate_article_from_texts_with_model_instance(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            GenerateArticleFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True, "response": {}}
            payload = GenerateArticleFromTextsModel(
                model_name="test-model", texts=["Tekst 1", "Tekst 2"]
            )
            resp = client.generate_article_from_texts(payload=payload)
            assert resp == {"status": True, "response": {}}
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["texts"] == ["Tekst 1", "Tekst 2"]

    def test_client_generate_article_from_texts_with_dict_payload(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            GenerateArticleFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            payload = {"model_name": "test-model", "texts": ["Tekst"]}
            resp = client.generate_article_from_texts(payload=payload)
            assert resp == {"status": True}
            mock_call.assert_called_once_with(payload)

    def test_client_generate_article_from_texts_with_args(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            GenerateArticleFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generate_article_from_texts(
                texts=["Tekst 1", "Tekst 2"], model="test-model"
            )
            assert resp == {"status": True}
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["texts"] == ["Tekst 1", "Tekst 2"]

    def test_client_generate_article_from_texts_with_default_model(self):
        client = LLMRouterClient(
            api="http://localhost:8080", default_model="def-model"
        )
        with mock.patch.object(
            GenerateArticleFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generate_article_from_texts(texts=["Tekst"])
            assert resp == {"status": True}
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "def-model"

    def test_client_generate_article_from_texts_no_args_raises(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with pytest.raises((NoArgsAndNoPayloadError, ValidationError)):
            client.generate_article_from_texts()


class TestGenerateArticleFromTextsAuthAndPrompts:
    """Tests for auth policy mapping and prompt files."""

    def test_endpoint_permission_map(self):
        assert "post:/api/generate_article_from_texts" in _ENDPOINT_PERMISSION_MAP
        assert (
            _ENDPOINT_PERMISSION_MAP["post:/api/generate_article_from_texts"]
            == "builtin"
        )

    def test_prompt_files_exist_and_contain_phrases(self):
        pl_prompt_path = (
            "resources/prompts/builtin/system/pl/article-from-texts.prompt"
        )
        en_prompt_path = (
            "resources/prompts/builtin/system/en/article-from-texts.prompt"
        )

        assert os.path.exists(pl_prompt_path)
        assert os.path.exists(en_prompt_path)

        with open(pl_prompt_path, encoding="utf-8") as f:
            pl_content = f.read().lower()
            assert "a4" in pl_content

        with open(en_prompt_path, encoding="utf-8") as f:
            en_content = f.read().lower()
            assert "a4" in en_content
