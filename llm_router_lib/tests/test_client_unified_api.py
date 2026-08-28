"""
Unit tests for the unified :class:`LLMRouterClient` endpoint contract.

Every endpoint method must behave according to the same rules:

* ``payload=<PydanticModel>`` is forwarded verbatim (``model_dump()``);
* ``payload=None`` + named kwargs builds a valid request payload;
* ``model=None`` falls back to the client ``default_model``;
* ``payload=None`` without required arguments raises
  :class:`NoArgsAndNoPayloadError`;
* ``payload=<dict>`` raises :class:`TypeError`;
* kwargs explicitly set to ``None`` never leak into the built payload
  (the Pydantic model defaults apply instead).

No live API is needed – service ``call_post`` methods are mocked.
Run with ``python -m unittest llm_router_lib.tests.test_client_unified_api``.
"""

import unittest
from unittest import mock

from llm_router_lib.client import LLMRouterClient
from llm_router_lib.data_models.builtin_chat import (
    ConversationWithModelRequest,
    ExtendedConversationWithModelRequest,
)
from llm_router_lib.data_models.builtin_utils import (
    Polarity3cModel,
    TranslateModel,
    SimplifyTextModel,
    GenerativeAnswerModel,
    GenerateArticleFromTextModel,
    CreateFullArticleFromTextsModel,
    GenerateArticleFromTextsModel,
    GenerateQuestionsModel,
    GenerateLabelModel,
)
from llm_router_lib.data_models.response import (
    ConversationResponse,
    ExtendedConversationResponse,
    Polarity3cResponse,
    TranslateResponse,
    SimplifyTextResponse,
    GenerativeAnswerResponse,
    GenerateArticleFromTextResponse,
    GenerateArticleFromTextsResponse,
    CreateFullArticleFromTextsResponse,
    GenerateQuestionsResponse,
    GenerateLabelResponse,
)
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_lib.services.conversation import (
    ConversationWithModelService,
    ExtendedConversationWithModelService,
)
from llm_router_lib.services.utils import (
    Polarity3cService,
    TranslateService,
    SimplifyTextService,
    GenerativeAnswerService,
    GenerateArticleFromTextService,
    CreateFullArticleFromTextsService,
    GenerateArticleFromTextsService,
    GenerateQuestionsService,
    GenerateLabelService,
)
from typing import Dict, Optional


class UnifiedMethodChecks:
    """
    Standard assertion set applied to a single client endpoint method.

    Subclasses configure:

    * ``method_name`` – client method under test,
    * ``service_cls`` – the service whose ``call_post`` is mocked,
    * ``request_model`` – the Pydantic request model,
    * ``response_cls`` – the Pydantic response model,
    * ``domain_kwargs`` – domain fields (no ``model``) making a valid request,
    * ``response_value`` – raw JSON returned by the mocked service.
    """

    method_name: str = ""
    service_cls: Optional[type] = None
    request_model: Optional[type] = None
    response_cls: Optional[type] = None
    domain_kwargs: dict = {}
    response_value: dict = {}

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def make_client(self, **init_kwargs) -> "LLMRouterClient":
        return LLMRouterClient(api="http://localhost:8080", **init_kwargs)

    def call_method(self, client: LLMRouterClient, **kwargs) -> object:
        return getattr(client, self.method_name)(**kwargs)

    @staticmethod
    def post_payload(mock_call: mock.MagicMock) -> Dict:
        return mock_call.call_args[0][0]

    # ------------------------------------------------------------------ #
    # standard tests
    # ------------------------------------------------------------------ #
    def test_payload_model_is_serialised_via_model_dump(self):
        request = self.request_model(model_name="test-model", **self.domain_kwargs)
        client = self.make_client()
        with mock.patch.object(
            self.service_cls, "call_post", return_value=self.response_value
        ) as mock_call:
            resp = self.call_method(client, payload=request)

        mock_call.assert_called_once()
        self.assertEqual(self.post_payload(mock_call), request.model_dump())
        self.assertIsInstance(resp, self.response_cls)

    def test_kwargs_build_valid_payload(self):
        client = self.make_client()
        with mock.patch.object(
            self.service_cls, "call_post", return_value=self.response_value
        ) as mock_call:
            resp = self.call_method(client, **self.domain_kwargs, model="test-model")

        self.assertIsInstance(resp, self.response_cls)
        payload = self.post_payload(mock_call)
        self.assertEqual(payload["model_name"], "test-model")
        for key, value in self.domain_kwargs.items():
            self.assertEqual(payload[key], value)

    def test_default_model_fallback(self):
        client = self.make_client(default_model="default-model")
        with mock.patch.object(
            self.service_cls, "call_post", return_value=self.response_value
        ) as mock_call:
            self.call_method(client, **self.domain_kwargs)

        self.assertEqual(self.post_payload(mock_call)["model_name"], "default-model")

    def test_no_args_and_no_payload_raises(self):
        client = self.make_client()
        with self.assertRaises(NoArgsAndNoPayloadError):
            self.call_method(client)

    def test_no_args_with_default_model_still_raises(self):
        client = self.make_client(default_model="default-model")
        with self.assertRaises(NoArgsAndNoPayloadError):
            self.call_method(client)

    def test_dict_payload_raises_type_error(self):
        client = self.make_client()
        with self.assertRaises(TypeError) as ctx:
            self.call_method(
                client, payload={"model_name": "test-model", **self.domain_kwargs}
            )
        self.assertIn("dict", str(ctx.exception).lower())

    def test_none_kwargs_fall_back_to_model_defaults(self):
        client = self.make_client()
        kwargs = dict(
            self.domain_kwargs,
            model="test-model",
            temperature=None,
            max_new_tokens=None,
        )
        with mock.patch.object(
            self.service_cls, "call_post", return_value=self.response_value
        ) as mock_call:
            self.call_method(client, **kwargs)

        payload = self.post_payload(mock_call)
        self.assertEqual(
            payload["temperature"],
            self.request_model.model_fields["temperature"].default,
        )
        self.assertEqual(
            payload["max_new_tokens"],
            self.request_model.model_fields["max_new_tokens"].default,
        )

    def test_generation_options_override_defaults(self):
        client = self.make_client()
        kwargs = dict(
            self.domain_kwargs, model="test-model", temperature=0.1, max_new_tokens=7
        )
        with mock.patch.object(
            self.service_cls, "call_post", return_value=self.response_value
        ) as mock_call:
            self.call_method(client, **kwargs)

        payload = self.post_payload(mock_call)
        self.assertEqual(payload["temperature"], 0.1)
        self.assertEqual(payload["max_new_tokens"], 7)


class ConversationWithModelTests(unittest.TestCase, UnifiedMethodChecks):
    method_name = "conversation_with_model"
    service_cls = ConversationWithModelService
    request_model = ConversationWithModelRequest
    response_cls = ConversationResponse
    domain_kwargs = {
        "user_last_statement": "Cześć, jak się masz?",
        "historical_messages": [
            {"role": "user", "content": "Witaj!"},
            {"role": "assistant", "content": "Witam!"},
        ],
    }
    response_value = {"status": True, "response": "Odpowiedź"}


class ExtendedConversationWithModelTests(unittest.TestCase, UnifiedMethodChecks):
    method_name = "extended_conversation_with_model"
    service_cls = ExtendedConversationWithModelService
    request_model = ExtendedConversationWithModelRequest
    response_cls = ExtendedConversationResponse
    domain_kwargs = {
        "user_last_statement": "Cześć, jak się masz?",
        "system_prompt": "Odpowiadaj jak mistrz Yoda.",
    }
    response_value = {"status": True, "response": "Odpowiedź"}


class Polarity3cTests(unittest.TestCase, UnifiedMethodChecks):
    method_name = "polarity_3c"
    service_cls = Polarity3cService
    request_model = Polarity3cModel
    response_cls = Polarity3cResponse
    domain_kwargs = {"texts": ["Bardzo dobry produkt!", "Słaby produkt."]}
    response_value = {"status": True, "response": []}


class TranslateTests(unittest.TestCase, UnifiedMethodChecks):
    method_name = "translate"
    service_cls = TranslateService
    request_model = TranslateModel
    response_cls = TranslateResponse
    domain_kwargs = {"texts": ["Hello", "World"]}
    response_value = {"status": True, "response": []}


class SimplifyTextTests(unittest.TestCase, UnifiedMethodChecks):
    method_name = "simplify_text"
    service_cls = SimplifyTextService
    request_model = SimplifyTextModel
    response_cls = SimplifyTextResponse
    domain_kwargs = {"texts": ["Zawiły urzędowy tekst."]}
    response_value = {"status": True, "response": []}


class GenerativeAnswerTests(unittest.TestCase, UnifiedMethodChecks):
    method_name = "generative_answer"
    service_cls = GenerativeAnswerService
    request_model = GenerativeAnswerModel
    response_cls = GenerativeAnswerResponse
    domain_kwargs = {
        "question_str": "Jakie kolory występują w tekstach?",
        "texts": ["Tęcza ma kolory."],
    }
    response_value = {"status": True, "response": "Odpowiedź"}


class GenerateArticleFromTextTests(unittest.TestCase, UnifiedMethodChecks):
    method_name = "generate_article_from_text"
    service_cls = GenerateArticleFromTextService
    request_model = GenerateArticleFromTextModel
    response_cls = GenerateArticleFromTextResponse
    domain_kwargs = {"text": "Tekst źródłowy"}
    response_value = {"status": True, "response": {}}


class GenerateArticleFromTextsTests(unittest.TestCase, UnifiedMethodChecks):
    method_name = "generate_article_from_texts"
    service_cls = GenerateArticleFromTextsService
    request_model = GenerateArticleFromTextsModel
    response_cls = GenerateArticleFromTextsResponse
    domain_kwargs = {"texts": ["Tekst 1", "Tekst 2"]}
    response_value = {"status": True, "response": {}}


class CreateFullArticleFromTextsTests(unittest.TestCase, UnifiedMethodChecks):
    method_name = "create_full_article_from_texts"
    service_cls = CreateFullArticleFromTextsService
    request_model = CreateFullArticleFromTextsModel
    response_cls = CreateFullArticleFromTextsResponse
    domain_kwargs = {"user_query": "Podsumuj teksty", "texts": ["Tekst 1"]}
    response_value = {"status": True, "response": {}}


class GenerateQuestionsTests(unittest.TestCase, UnifiedMethodChecks):
    method_name = "generate_questions"
    service_cls = GenerateQuestionsService
    request_model = GenerateQuestionsModel
    response_cls = GenerateQuestionsResponse
    domain_kwargs = {"texts": ["Tekst 1"]}
    response_value = {"status": True, "response": []}

    def test_number_of_questions_defaults_from_model(self):
        client = self.make_client()
        with mock.patch.object(
            self.service_cls, "call_post", return_value=self.response_value
        ) as mock_call:
            self.call_method(client, **self.domain_kwargs, model="test-model")

        payload = self.post_payload(mock_call)
        self.assertEqual(
            payload["number_of_questions"],
            self.request_model.model_fields["number_of_questions"].default,
        )


class GenerateLabelTests(unittest.TestCase, UnifiedMethodChecks):
    method_name = "generate_label"
    service_cls = GenerateLabelService
    request_model = GenerateLabelModel
    response_cls = GenerateLabelResponse
    domain_kwargs = {"texts": ["Smartfony", "Aparaty"]}
    response_value = {"status": True, "response": "Etykieta"}


if __name__ == "__main__":
    unittest.main()
