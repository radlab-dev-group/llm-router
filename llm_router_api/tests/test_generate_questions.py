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
    GenerateQuestionFromTextsModel,
    GENERATE_Q_REQ,
    GENERATE_Q_OPT,
)
from llm_router_lib.services.utils import (
    GenerateQuestionsFromTextsService,
    GenerateQuestionFromTextsService,
)
from llm_router_lib.client import LLMRouterClient
from llm_router_lib.exceptions import NoArgsAndNoPayloadError


class TestGenerateQuestionsDataModel(unittest.TestCase):
    """Tests for GenerateQuestionFromTextsModel pydantic validation."""

    def test_valid_payload(self):
        model = GenerateQuestionFromTextsModel(
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
        model = GenerateQuestionFromTextsModel(
            model_name="test-model",
            texts=["Tekst 1"],
        )
        self.assertEqual(model.number_of_questions, 1)

    def test_missing_model_name_raises(self):
        with self.assertRaises(ValidationError):
            GenerateQuestionFromTextsModel(texts=["Tekst"])

    def test_missing_texts_raises(self):
        with self.assertRaises(ValidationError):
            GenerateQuestionFromTextsModel(model_name="test-model")

    def test_constants(self):
        self.assertIn("texts", GENERATE_Q_REQ)
        self.assertIn("model_name", GENERATE_Q_REQ)
        self.assertIn("number_of_questions", GENERATE_Q_OPT)


class TestGenerateQuestionsServiceAndClient(unittest.TestCase):
    """Tests for GenerateQuestionsFromTextsService and LLMRouterClient."""

    def test_service_attributes(self):
        self.assertEqual(
            GenerateQuestionsFromTextsService.endpoint,
            "/api/generate_questions",
        )
        self.assertEqual(
            GenerateQuestionsFromTextsService.model_cls,
            GenerateQuestionFromTextsModel,
        )
        self.assertIs(
            GenerateQuestionFromTextsService, GenerateQuestionsFromTextsService
        )

    def test_client_generate_questions_with_model_instance(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            GenerateQuestionsFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True, "response": []}
            payload = GenerateQuestionFromTextsModel(
                model_name="test-model",
                texts=["Przykładowy tekst"],
                number_of_questions=2,
            )
            resp = client.generate_questions_from_texts(payload=payload)
            self.assertEqual(resp, {"status": True, "response": []})
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            self.assertEqual(call_arg["model_name"], "test-model")
            self.assertEqual(call_arg["texts"], ["Przykładowy tekst"])
            self.assertEqual(call_arg["number_of_questions"], 2)

    def test_client_generate_questions_with_dict_payload(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            GenerateQuestionsFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            payload = {
                "model_name": "test-model",
                "texts": ["Tekst"],
                "number_of_questions": 1,
            }
            resp = client.generate_questions_from_texts(payload=payload)
            self.assertEqual(resp, {"status": True})
            mock_call.assert_called_once_with(payload)

    def test_client_generate_questions_with_args(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            GenerateQuestionsFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generate_questions_from_texts(
                texts=["Tekst A", "Tekst B"],
                number_of_questions=3,
                model="test-model",
            )
            self.assertEqual(resp, {"status": True})
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            self.assertEqual(call_arg["model_name"], "test-model")
            self.assertEqual(call_arg["texts"], ["Tekst A", "Tekst B"])
            self.assertEqual(call_arg["number_of_questions"], 3)

    def test_client_generate_questions_alias(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with mock.patch.object(
            GenerateQuestionsFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generate_questions(
                texts=["Tekst A"],
                model="test-model",
            )
            self.assertEqual(resp, {"status": True})
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            self.assertEqual(call_arg["model_name"], "test-model")
            self.assertEqual(call_arg["texts"], ["Tekst A"])
            self.assertEqual(call_arg["number_of_questions"], 1)

    def test_client_generate_questions_with_default_model(self):
        client = LLMRouterClient(
            api="http://localhost:8080", default_model="def-model"
        )
        with mock.patch.object(
            GenerateQuestionsFromTextsService, "call_post"
        ) as mock_call:
            mock_call.return_value = {"status": True}
            resp = client.generate_questions_from_texts(texts=["Tekst"])
            self.assertEqual(resp, {"status": True})
            mock_call.assert_called_once()
            call_arg = mock_call.call_args[0][0]
            self.assertEqual(call_arg["model_name"], "def-model")

    def test_client_generate_questions_no_args_raises(self):
        client = LLMRouterClient(api="http://localhost:8080")
        with self.assertRaises((NoArgsAndNoPayloadError, ValidationError)):
            client.generate_questions_from_texts()


if __name__ == "__main__":
    unittest.main()
