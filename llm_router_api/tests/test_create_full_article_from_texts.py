"""
Tests for the create_full_article_from_texts endpoint and client library components.
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
    CreateFullArticleFromTextsModel,
    CREATE_FULL_ARTICLE_FROM_TEXTS_REQ,
    CREATE_FULL_ARTICLE_FROM_TEXTS_OPT,
)
from llm_router_lib.services.utils import CreateFullArticleFromTextsService
from llm_router_lib.client import LLMRouterClient
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_api.endpoints.builtin.builtin_utils import CreateFullArticleFromTexts
from llm_router_api.core.auth.policies.engine import _ENDPOINT_PERMISSION_MAP


class TestCreateFullArticleFromTextsDataModel:
    """Tests for CreateFullArticleFromTextsModel pydantic validation."""

    def test_valid_payload(self):
        model = CreateFullArticleFromTextsModel(
            model_name="test-model",
            user_query="Napisz artykuł o pogodzie",
            texts=["Sturmtief Detlef", "Sturmflutwarnung"],
            article_type="news",
        )
        assert model.model_name == "test-model"
        assert model.user_query == "Napisz artykuł o pogodzie"
        assert model.texts == ["Sturmtief Detlef", "Sturmflutwarnung"]
        assert model.article_type == "news"

    def test_texts_default_to_none(self):
        model = CreateFullArticleFromTextsModel(
            model_name="test-model",
            user_query="Napisz artykuł",
            texts=[],
        )
        assert model.texts == []
        assert model.article_type is None

    def test_missing_model_name_raises(self):
        with pytest.raises(ValidationError):
            CreateFullArticleFromTextsModel(user_query="Query", texts=["Tekst"])

    def test_missing_user_query_raises(self):
        with pytest.raises(ValidationError):
            CreateFullArticleFromTextsModel(model_name="test-model", texts=["Tekst"])

    def test_texts_is_optional(self):
        # ``texts`` is optional (defaults to None) on this model.
        model = CreateFullArticleFromTextsModel(
            model_name="test-model", user_query="Query"
        )
        assert model.texts is None

    def test_constants(self):
        assert "user_query" in CREATE_FULL_ARTICLE_FROM_TEXTS_REQ
        assert "texts" in CREATE_FULL_ARTICLE_FROM_TEXTS_REQ
        assert "model_name" in CREATE_FULL_ARTICLE_FROM_TEXTS_REQ
        assert "article_type" in CREATE_FULL_ARTICLE_FROM_TEXTS_OPT


class TestCreateFullArticleFromTextsEndpoint:
    """Tests for the CreateFullArticleFromTexts endpoint class."""

    @pytest.fixture
    def endpoint(self):
        return CreateFullArticleFromTexts(
            logger_file_name=None,
            prompt_handler=None,
            model_handler=None,
        )

    def test_endpoint_attributes(self, endpoint):
        assert endpoint.name == "create_full_article_from_texts"
        assert endpoint.method == "POST"
        assert "builtin" in endpoint._ep_types_str
        assert endpoint.SYSTEM_PROMPT_NAME == {
            "pl": "builtin/system/pl/full-article",
            "en": "builtin/system/en/full-article",
        }

    def test_prepare_payload(self, endpoint):
        params = {
            "model_name": "test-model",
            "user_query": "Podsumuj wydarzenia dnia",
            "texts": ["Wydanie 1", "Wydanie 2"],
            "article_type": "review",
        }
        payload = endpoint.prepare_payload(params)
        assert payload is not None
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert "texts" not in payload
        assert "user_query" not in payload
        assert "article_type" not in payload
        assert payload["messages"] == [
            {"role": "user", "content": "Wydanie 1\n\nWydanie 2"}
        ]
        assert payload["map_prompt"] == {
            "##USER_Q_STR##": "Podsumuj wydarzenia dnia"
        }
        assert payload["prompt_str_postfix"] == "review"

    def test_prepare_response_function(self, endpoint):
        endpoint._start_time = time.time()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Pełny artykuł."}}]
        }

        result = endpoint._prepare_response_function(mock_response)
        assert "response" in result
        assert "generation_time" in result
        assert result["response"] == {"article_text": "Pełny artykuł."}


class TestCreateFullArticleFromTextsServiceAndClient:
    """Tests for CreateFullArticleFromTextsService and LLMRouterClient."""

    def test_service_attributes(self):
        assert (
            CreateFullArticleFromTextsService.endpoint
            == "/api/create_full_article_from_texts"
        )
        assert (
            CreateFullArticleFromTextsService.model_cls
            is CreateFullArticleFromTextsModel
        )

    def test_client_create_full_article_from_texts_with_model_instance(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            CreateFullArticleFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True, "response": {}}
            payload = CreateFullArticleFromTextsModel(
                model_name="test-model",
                user_query="Podsumuj",
                texts=["Tekst 1", "Tekst 2"],
            )
            resp = client.create_full_article_from_texts(payload=payload)
            assert resp == {"status": True, "response": {}}
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["user_query"] == "Podsumuj"
            assert call_arg["texts"] == ["Tekst 1", "Tekst 2"]

    def test_client_create_full_article_from_texts_with_dict_payload(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            CreateFullArticleFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            payload = {
                "model_name": "test-model",
                "user_query": "Podsumuj",
                "texts": ["Tekst"],
            }
            resp = client.create_full_article_from_texts(payload=payload)
            assert resp == {"status": True}
            mock_call.assert_called_once_with(payload)

    def test_client_create_full_article_from_texts_with_args(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            CreateFullArticleFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.create_full_article_from_texts(
                user_query="Podsumuj",
                texts=["Tekst 1", "Tekst 2"],
                article_type="review",
                model="test-model",
            )
            assert resp == {"status": True}
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["user_query"] == "Podsumuj"
            assert call_arg["texts"] == ["Tekst 1", "Tekst 2"]
            assert call_arg["article_type"] == "review"

    def test_client_create_full_article_from_texts_with_default_model(self):
        client = LLMRouterClient(
            api="http://localhost:8080", default_model="def-model"
        )
        with mock.patch.object(
            CreateFullArticleFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.create_full_article_from_texts(
                user_query="Podsumuj", texts=["Tekst"]
            )
            assert resp == {"status": True}
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "def-model"

    def test_client_create_full_article_from_texts_no_args_raises(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with pytest.raises((NoArgsAndNoPayloadError, ValidationError)):
            client.create_full_article_from_texts()


class TestCreateFullArticleFromTextsAuthAndPrompts:
    """Tests for auth policy mapping and prompt files."""

    def test_endpoint_permission_map(self):
        assert "post:/api/create_full_article_from_texts" in _ENDPOINT_PERMISSION_MAP
        assert (
            _ENDPOINT_PERMISSION_MAP["post:/api/create_full_article_from_texts"]
            == "builtin"
        )

    def test_prompt_files_exist_and_contain_phrases(self):
        pl_prompt_path = "resources/prompts/builtin/system/pl/full-article.prompt"
        en_prompt_path = "resources/prompts/builtin/system/en/full-article.prompt"

        assert os.path.exists(pl_prompt_path)
        assert os.path.exists(en_prompt_path)

        with open(pl_prompt_path, encoding="utf-8") as f:
            pl_content = f.read().lower()
            assert "artykuł" in pl_content

        with open(en_prompt_path, encoding="utf-8") as f:
            en_content = f.read().lower()
            assert "article" in en_content
