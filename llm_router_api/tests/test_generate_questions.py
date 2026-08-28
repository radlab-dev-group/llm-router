"""
Tests for generate_questions endpoint and client library components.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock
from pydantic import ValidationError

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from llm_router_lib.data_models.builtin_utils import (
    GenerateQuestionsModel,
    GENERATE_QUESTIONS_REQ,
    GENERATE_QUESTIONS_OPT,
)
from llm_router_lib.services.utils import (
    GenerateQuestionsService,
)
from llm_router_lib.client import LLMRouterClient
from llm_router_lib.data_models.response import GenerateQuestionsResponse
from llm_router_lib.exceptions import NoArgsAndNoPayloadError


class TestGenerateQuestionsDataModel(unittest.TestCase):
    """Tests for GenerateQuestionsModel pydantic validation."""

    def test_valid_payload(self):
        model = GenerateQuestionsModel(
            model_name="test-model",
            texts=["Tekst 1", "Tekst 2"],
            number_of_questions=3,
            temperature=0.7,
        )
        self.assertEqual(model.model_name, "test-model")
        self.assertEqual(len(model.texts), 2)
        self.assertEqual(model.texts[0], "Tekst 1")
        self.assertEqual(model.number_of_questions, 3)
        self.assertEqual(model.temperature, 0.7)

    def test_default_number_of_questions(self):
        model = GenerateQuestionsModel(
            model_name="test-model",
            texts=["Tekst 1"],
        )
        self.assertEqual(model.number_of_questions, 1)

    def test_missing_model_name_raises(self):
        with self.assertRaises(ValidationError):
            GenerateQuestionsModel(texts=["Tekst"])

    def test_missing_texts_raises(self):
        with self.assertRaises(ValidationError):
            GenerateQuestionsModel(model_name="test-model")

    def test_constants(self):
        self.assertIn("texts", GENERATE_QUESTIONS_REQ)
        self.assertIn("model_name", GENERATE_QUESTIONS_REQ)
        self.assertIn("number_of_questions", GENERATE_QUESTIONS_OPT)


class TestGenerateQuestionsServiceAndClient(unittest.TestCase):
    """Tests for GenerateQuestionsService and LLMRouterClient."""

    def test_service_attributes(self):
        self.assertEqual(
            GenerateQuestionsService.endpoint,
            "/api/generate_questions",
        )
        self.assertEqual(
            GenerateQuestionsService.model_cls,
            GenerateQuestionsModel,
        )

    def test_client_generate_questions_with_model_instance(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(GenerateQuestionsService, "call_post") as mock_call:
            mock_call.return_value = {"status": True, "response": []}
            payload = GenerateQuestionsModel(
                model_name="test-model",
                texts=["Przykładowy tekst"],
                number_of_questions=2,
            )
            resp = client.generate_questions(payload=payload)
            self.assertIsInstance(resp, GenerateQuestionsResponse)
            self.assertEqual(resp.response, [])
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            self.assertEqual(call_arg["model_name"], "test-model")
            self.assertEqual(call_arg["texts"], ["Przykładowy tekst"])
            self.assertEqual(call_arg["number_of_questions"], 2)

    def test_client_generate_questions_with_dict_payload_raises_type_error(self):
        client = LLMRouterClient(api="http://localhost:8080")
        payload = {
            "model_name": "test-model",
            "texts": ["Tekst"],
            "number_of_questions": 1,
        }
        with self.assertRaises(TypeError):
            client.generate_questions(payload=payload)

    def test_client_generate_questions_with_args(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(GenerateQuestionsService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generate_questions(
                texts=["Tekst A", "Tekst B"],
                number_of_questions=3,
                model="test-model",
            )
            self.assertIsInstance(resp, GenerateQuestionsResponse)
            self.assertEqual(resp.response, [])
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            self.assertEqual(call_arg["model_name"], "test-model")
            self.assertEqual(call_arg["texts"], ["Tekst A", "Tekst B"])
            self.assertEqual(call_arg["number_of_questions"], 3)

    def test_client_generate_questions_alias(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(GenerateQuestionsService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generate_questions(
                texts=["Tekst A"],
                model="test-model",
            )
            self.assertIsInstance(resp, GenerateQuestionsResponse)
            self.assertEqual(resp.response, [])
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            self.assertEqual(call_arg["model_name"], "test-model")
            self.assertEqual(call_arg["texts"], ["Tekst A"])
            self.assertEqual(call_arg["number_of_questions"], 1)

    def test_client_generate_questions_with_default_model(self):
        client = LLMRouterClient(
            api="http://localhost:8080", default_model="def-model"
        )
        with mock.patch.object(GenerateQuestionsService, "call_post") as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generate_questions(texts=["Tekst"])
            self.assertIsInstance(resp, GenerateQuestionsResponse)
            self.assertEqual(resp.response, [])
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            self.assertEqual(call_arg["model_name"], "def-model")

    def test_client_generate_questions_no_args_raises(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with self.assertRaises((NoArgsAndNoPayloadError, ValidationError)):
            client.generate_questions()


if __name__ == "__main__":
    unittest.main()
