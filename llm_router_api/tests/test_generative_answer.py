"""
Tests for the generative_answer endpoint and client library components.
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
    GenerativeAnswerModel,
    GENERATIVE_ANSWER_REQ,
    GENERATIVE_ANSWER_OPT,
)
from llm_router_lib.services.utils import GenerativeAnswerService
from llm_router_lib.client import LLMRouterClient
from llm_router_lib.data_models.response import GenerativeAnswerResponse
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_api.endpoints.builtin.builtin_utils import GenerativeAnswer
from llm_router_api.core.auth.policies.engine import _ENDPOINT_PERMISSION_MAP


class TestGenerativeAnswerDataModel:
    """Tests for GenerativeAnswerModel pydantic validation."""

    def test_valid_payload_list_texts(self):
        model = GenerativeAnswerModel(
            model_name="test-model",
            question_str="Co się wydarzyło?",
            texts=["Tekst 1", "Tekst 2"],
        )
        assert model.model_name == "test-model"
        assert model.question_str == "Co się wydarzyło?"
        assert model.texts == ["Tekst 1", "Tekst 2"]
        assert model.doc_name_in_answer is False

    def test_valid_payload_dict_texts(self):
        model = GenerativeAnswerModel(
            model_name="test-model",
            question_str="Co się wydarzyło?",
            texts={"artykul.html": ["Fragment 1", "Fragment 2"]},
            doc_name_in_answer=True,
            question_prompt="Odpowiedz krótko",
            system_prompt="Odpowiadaj jak Yoda",
        )
        assert model.texts == {"artykul.html": ["Fragment 1", "Fragment 2"]}
        assert model.doc_name_in_answer is True
        assert model.question_prompt == "Odpowiedz krótko"
        assert model.system_prompt == "Odpowiadaj jak Yoda"

    def test_missing_model_name_raises(self):
        with pytest.raises(ValidationError):
            GenerativeAnswerModel(question_str="Pytanie", texts=["Tekst"])

    def test_missing_question_str_raises(self):
        with pytest.raises(ValidationError):
            GenerativeAnswerModel(model_name="test-model", texts=["Tekst"])

    def test_missing_texts_raises(self):
        with pytest.raises(ValidationError):
            GenerativeAnswerModel(model_name="test-model", question_str="Pytanie")

    def test_constants(self):
        assert "question_str" in GENERATIVE_ANSWER_REQ
        assert "texts" in GENERATIVE_ANSWER_REQ
        assert "model_name" in GENERATIVE_ANSWER_REQ
        assert "question_prompt" in GENERATIVE_ANSWER_OPT
        assert "system_prompt" in GENERATIVE_ANSWER_OPT


class TestGenerativeAnswerEndpoint:
    """Tests for the GenerativeAnswer endpoint class."""

    @pytest.fixture
    def endpoint(self):
        return GenerativeAnswer(
            logger_file_name=None,
            prompt_handler=None,
            model_handler=None,
        )

    def test_endpoint_attributes(self, endpoint):
        assert endpoint.name == "generative_answer"
        assert endpoint.method == "POST"
        assert "builtin" in endpoint._ep_types_str
        assert endpoint.SYSTEM_PROMPT_NAME == {
            "pl": "builtin/system/pl/answer-from-context-simple",
            "en": "builtin/system/en/answer-from-context-simple",
        }

    def test_prepare_payload_list_texts(self, endpoint):
        params = {
            "model_name": "test-model",
            "question_str": "Co się wydarzyło?",
            "texts": ["Tekst 1", "Tekst 2"],
        }
        payload = endpoint.prepare_payload(params)
        assert payload is not None
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert "texts" not in payload
        assert "question_str" not in payload
        assert payload["messages"] == [
            {"role": "user", "content": "Tekst 1\n\nTekst 2"}
        ]
        assert payload["map_prompt"] == {"##QUESTION_STR##": "Co się wydarzyło?"}

    def test_prepare_payload_dict_texts_with_doc_name(self, endpoint):
        params = {
            "model_name": "test-model",
            "question_str": "Co się wydarzyło?",
            "texts": {"artykul.html": ["Fragment 1"]},
            "doc_name_in_answer": True,
        }
        payload = endpoint.prepare_payload(params)
        assert payload is not None
        content = payload["messages"][0]["content"]
        assert "Document name: artykul.html" in content
        assert "Fragment 1" in content

    def test_prepare_response_function(self, endpoint):
        endpoint._start_time = time.time()

        mock_response = mock.MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Wystąpił sturm."}}]
        }

        result = endpoint._prepare_response_function(mock_response)
        assert "response" in result
        assert "generation_time" in result
        assert result["response"] == "Wystąpił sturm."


class TestGenerativeAnswerServiceAndClient:
    """Tests for GenerativeAnswerService and LLMRouterClient.generative_answer."""

    def test_service_attributes(self):
        assert GenerativeAnswerService.endpoint == "/api/generative_answer"
        assert GenerativeAnswerService.model_cls is GenerativeAnswerModel

    def test_client_generative_answer_with_model_instance(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(GenerativeAnswerService, "call_post") as mock_call:
            mock_call.return_value = {"status": True, "response": "Odpowiedź"}
            payload = GenerativeAnswerModel(
                model_name="test-model",
                question_str="Co się wydarzyło?",
                texts=["Tekst"],
            )
            resp = client.generative_answer(payload=payload)
            assert isinstance(resp, GenerativeAnswerResponse)
            assert resp.response == "Odpowiedź"
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["question_str"] == "Co się wydarzyło?"

    def test_client_generative_answer_with_dict_payload(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(GenerativeAnswerService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            payload = {
                "model_name": "test-model",
                "question_str": "Co się wydarzyło?",
                "texts": ["Tekst"],
            }
            resp = client.generative_answer(payload=payload)
            assert isinstance(resp, GenerativeAnswerResponse)
            assert resp.response is None
            mock_call.assert_called_once_with(payload)

    def test_client_generative_answer_with_args(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(GenerativeAnswerService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generative_answer(
                question_str="Co się wydarzyło?",
                texts=["Tekst 1", "Tekst 2"],
                model="test-model",
            )
            assert isinstance(resp, GenerativeAnswerResponse)
            assert resp.response is None
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["question_str"] == "Co się wydarzyło?"
            assert call_arg["texts"] == ["Tekst 1", "Tekst 2"]

    def test_client_generative_answer_with_default_model(self):
        client = LLMRouterClient(
            api="http://localhost:8080", default_model="def-model"
        )
        with mock.patch.object(GenerativeAnswerService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generative_answer(question_str="Pytanie", texts=["Tekst"])
            assert isinstance(resp, GenerativeAnswerResponse)
            assert resp.response is None
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "def-model"

    def test_client_generative_answer_no_args_raises(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with pytest.raises((NoArgsAndNoPayloadError, ValidationError)):
            client.generative_answer()


class TestGenerativeAnswerAuthAndPrompts:
    """Tests for auth policy mapping and prompt files."""

    def test_endpoint_permission_map(self):
        assert "post:/api/generative_answer" in _ENDPOINT_PERMISSION_MAP
        assert _ENDPOINT_PERMISSION_MAP["post:/api/generative_answer"] == "builtin"

    def test_prompt_files_exist_and_contain_phrases(self):
        pl_prompt_path = (
            "resources/prompts/builtin/system/pl/answer-from-context-simple.prompt"
        )
        en_prompt_path = (
            "resources/prompts/builtin/system/en/answer-from-context-simple.prompt"
        )

        assert os.path.exists(pl_prompt_path)
        assert os.path.exists(en_prompt_path)

        with open(pl_prompt_path, encoding="utf-8") as f:
            pl_content = f.read().lower()
            assert "pytania" in pl_content

        with open(en_prompt_path, encoding="utf-8") as f:
            en_content = f.read().lower()
            assert "answers" in en_content
