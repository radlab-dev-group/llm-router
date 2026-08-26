"""
Tests for polarity_3c endpoint and client library components.
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
    Polarity3cModel,
    POLARITY_3C_REQ,
    POLARITY_3C_OPT,
)
from llm_router_lib.services.utils import Polarity3cService
from llm_router_lib.client import LLMRouterClient
from llm_router_lib.data_models.response import Polarity3cResponse
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_api.endpoints.builtin.builtin_utils import Polarity3c
from llm_router_api.core.auth.policies.engine import _ENDPOINT_PERMISSION_MAP


class TestPolarity3cDataModel:
    """Tests for Polarity3cModel pydantic validation."""

    def test_valid_payload(self):
        model = Polarity3cModel(
            model_name="test-model",
            texts=["Tekst pozytywny", "Tekst negatywny"],
            temperature=0.0,
            max_new_tokens=64,
        )
        assert model.model_name == "test-model"
        assert len(model.texts) == 2
        assert model.texts[0] == "Tekst pozytywny"
        assert model.temperature == 0.0
        assert model.max_new_tokens == 64

    def test_missing_model_name_raises(self):
        with pytest.raises(ValidationError):
            Polarity3cModel(texts=["Tekst"])

    def test_missing_texts_raises(self):
        with pytest.raises(ValidationError):
            Polarity3cModel(model_name="test-model")

    def test_constants(self):
        assert "texts" in POLARITY_3C_REQ
        assert "model_name" in POLARITY_3C_REQ
        assert "temperature" in POLARITY_3C_OPT
        assert "max_new_tokens" in POLARITY_3C_OPT


class TestPolarity3cEndpoint:
    """Tests for Polarity3c endpoint class."""

    @pytest.fixture
    def endpoint(self):
        return Polarity3c(
            logger_file_name=None,
            prompt_handler=None,
            model_handler=None,
        )

    def test_endpoint_attributes(self, endpoint):
        assert endpoint.name == "polarity_3c"
        assert endpoint.method == "POST"
        assert "builtin" in endpoint._ep_types_str
        assert endpoint._call_for_each_user_msg is True
        assert endpoint.SYSTEM_PROMPT_NAME == {
            "pl": "builtin/system/pl/polarity-3c",
            "en": "builtin/system/en/polarity-3c",
        }

    def test_prepare_payload(self, endpoint):
        params = {
            "model_name": "test-model",
            "texts": ["Tekst 1", "Tekst 2"],
            "temperature": 0.5,
        }
        payload = endpoint.prepare_payload(params)
        assert payload is not None
        assert payload["model"] == "test-model"
        assert payload["stream"] is False
        assert "texts" not in payload
        assert len(payload["messages"]) == 2
        assert payload["messages"][0] == {"role": "user", "content": "Tekst 1"}
        assert payload["messages"][1] == {"role": "user", "content": "Tekst 2"}

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("positive", "positive"),
            ("negative", "negative"),
            ("ambivalent", "ambivalent"),
            ("POSITIVE", "positive"),
            ("  Positive  ", "positive"),
            ("positive.", "positive"),
            ('"negative"', "negative"),
            ("The polarity is ambivalent.", "ambivalent"),
            ("Classification: positive", "positive"),
            ("wynik: negative", "negative"),
            ("ambivalent text here", "ambivalent"),
            ("unknown_class", "unknown_class"),
        ],
    )
    def test_extract_polarity(self, raw, expected):
        assert Polarity3c._extract_polarity(raw) == expected

    def test_prepare_response_function(self, endpoint):
        mock_response_1 = mock.MagicMock()
        mock_response_1.json.return_value = {
            "choices": [{"message": {"content": "positive"}}]
        }
        mock_response_2 = mock.MagicMock()
        mock_response_2.json.return_value = {
            "choices": [{"message": {"content": "negative"}}]
        }
        mock_response_3 = mock.MagicMock()
        mock_response_3.json.return_value = {
            "choices": [{"message": {"content": "ambivalent"}}]
        }

        endpoint._start_time = time.time()

        responses = [mock_response_1, mock_response_2, mock_response_3]
        contents = [
            "Wspaniały produkt!",
            "Okropna obsługa.",
            "Neutralny opis sytuacji.",
        ]

        result = endpoint._prepare_response_function(responses, contents)
        assert "response" in result
        assert "generation_time" in result
        assert len(result["response"]) == 3
        assert result["response"][0] == {
            "original": "Wspaniały produkt!",
            "polarity": "positive",
        }
        assert result["response"][1] == {
            "original": "Okropna obsługa.",
            "polarity": "negative",
        }
        assert result["response"][2] == {
            "original": "Neutralny opis sytuacji.",
            "polarity": "ambivalent",
        }


class TestPolarity3cServiceAndClient:
    """Tests for Polarity3cService and LLMRouterClient.polarity_3c."""

    def test_service_attributes(self):
        assert Polarity3cService.endpoint == "/api/polarity_3c"
        assert Polarity3cService.model_cls == Polarity3cModel

    def test_client_polarity_3c_with_model_instance(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(Polarity3cService, "call_post") as mock_call:
            mock_call.return_value = {"status": True, "response": []}
            payload = Polarity3cModel(
                model_name="test-model",
                texts=["Dobry tekst"],
            )
            resp = client.polarity_3c(payload=payload)
            assert isinstance(resp, Polarity3cResponse)
            assert resp.response == []
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["texts"] == ["Dobry tekst"]

    def test_client_polarity_3c_with_dict_payload(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(Polarity3cService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            payload = {
                "model_name": "test-model",
                "texts": ["Tekst"],
            }
            resp = client.polarity_3c(payload=payload)
            assert isinstance(resp, Polarity3cResponse)
            assert resp.response == []
            mock_call.assert_called_once_with(payload)

    def test_client_polarity_3c_with_args(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(Polarity3cService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.polarity_3c(
                texts=["Tekst A", "Tekst B"],
                model="test-model",
                temperature=0.1,
            )
            assert isinstance(resp, Polarity3cResponse)
            assert resp.response == []
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "test-model"
            assert call_arg["texts"] == ["Tekst A", "Tekst B"]
            assert call_arg["temperature"] == 0.1

    def test_client_polarity_3c_with_default_model(self):
        client = LLMRouterClient(
            api="http://localhost:8080", default_model="def-model"
        )
        with mock.patch.object(Polarity3cService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.polarity_3c(texts=["Tekst"])
            assert isinstance(resp, Polarity3cResponse)
            assert resp.response == []
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            assert call_arg["model_name"] == "def-model"

    def test_client_polarity_3c_no_args_raises(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with pytest.raises((NoArgsAndNoPayloadError, ValidationError)):
            client.polarity_3c()


class TestPolarity3cAuthAndPrompts:
    """Tests for auth policy mapping and prompt files."""

    def test_endpoint_permission_map(self):
        assert "post:/api/polarity_3c" in _ENDPOINT_PERMISSION_MAP
        assert _ENDPOINT_PERMISSION_MAP["post:/api/polarity_3c"] == "builtin"

    def test_prompt_files_exist_and_contain_classes(self):
        pl_prompt_path = "resources/prompts/builtin/system/pl/polarity-3c.prompt"
        en_prompt_path = "resources/prompts/builtin/system/en/polarity-3c.prompt"

        assert os.path.exists(pl_prompt_path)
        assert os.path.exists(en_prompt_path)

        with open(pl_prompt_path, encoding="utf-8") as f:
            pl_content = f.read().lower()
            assert "positive" in pl_content
            assert "negative" in pl_content
            assert "ambivalent" in pl_content

        with open(en_prompt_path, encoding="utf-8") as f:
            en_content = f.read().lower()
            assert "positive" in en_content
            assert "negative" in en_content
            assert "ambivalent" in en_content
