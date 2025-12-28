"""
Utility endpoints that expose built‑in generative capabilities.

Each endpoint validates its input via a pydantic model, forwards the request to
the generic ``EndpointWithHttpRequestI`` machinery, and post‑processes the
response into a clean JSON payload.
"""

import os
import time

from typing import Optional, Dict, Any, List

from rdl_ml_utils.handlers.prompt_handler import PromptHandler


from llm_router_lib.data_models.builtin_utils import (
    GenerateQuestionFromTextsModel,
    GENERATE_Q_REQ,
    GENERATE_Q_OPT,
    GenerateArticleFromTextModel,
    GENERATE_ART_REQ,
    GENERATE_ART_OPT,
    TRANSLATE_TEXT_REQ,
    TRANSLATE_TEXT_OPT,
    TranslateTextModel,
    SIMPLIFY_TEXT_REQ,
    SIMPLIFY_TEXT_OPT,
    SimplifyTextModel,
    CreateArticleFromNewsList,
    FULL_ARTICLE_REQ,
    FULL_ARTICLE_OPT,
    CONTEXT_ANSWER_REQ,
    CONTEXT_ANSWER_OPT,
    AnswerBasedOnTheContextModel,
)
from llm_router_api.core.decorators import EP
from llm_router_api.core.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.endpoints.endpoint_i import EndpointWithHttpRequestI


class ApiVersion(EndpointWithHttpRequestI):
    VERSION_FILE = ".version"

    EP_DONT_NEED_GUARDRAIL_AND_MASKING = True

    REQUIRED_ARGS = []
    OPTIONAL_ARGS = []
    SYSTEM_PROMPT_NAME = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "version",
    ):
        """
        Create a health‑check endpoint that returns the router version.

        Parameters
        ----------
        logger_file_name : Optional[str]
            Optional file name for the logger.
        logger_level : Optional[str]
            Logging verbosity; defaults to :data:`REST_API_LOG_LEVEL`.
        model_handler : Optional[ModelHandler]
            Unused for this endpoint but required by the base class.
        prompt_handler : Optional[PromptHandler]
            Unused for this endpoint but required by the base class.
        ep_name : str
            URL fragment for the endpoint (default ``"version"``).
        """
        super().__init__(
            method="GET",
            ep_name=ep_name,
            logger_file_name=logger_file_name,
            logger_level=logger_level,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            api_types=["ollama", "vllm", "openai", "llmstudio", "anthropic"],
        )

        self.version = "0.0.1"
        if os.path.exists(self.VERSION_FILE):
            with open(self.VERSION_FILE) as f:
                self.version = f.read().strip()

        self.logger.info(f"  -> Running LLM-Router version: {self.version}")

    @EP.response_time
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any] | str]:
        """
        Return the router version as a JSON payload.

        The method sets ``direct_return`` so that the Flask registrar sends the
        dictionary directly without additional wrapping.

        Returns
        -------
        dict
            ``{"version": "<semver>"}``.
        """
        self.direct_return = True
        return {"version": self.version}


class GenerateQuestionsFromTexts(EndpointWithHttpRequestI):
    REQUIRED_ARGS = GENERATE_Q_REQ
    OPTIONAL_ARGS = GENERATE_Q_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/generate-questions",
        "en": "builtin/system/en/generate-questions",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "generate_questions",
    ):
        """
        Initialize the “generate questions” endpoint.

        Parameters are analogous to other builtin endpoints.
        """
        super().__init__(
            ep_name=ep_name,
            api_types=["builtin"],
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            direct_return=False,
            call_for_each_user_msg=True,
        )

        self._prepare_response_function = self.__prepare_response_function

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Validate input and build the request payload for question generation.

        The method extracts the model name, optional streaming flag, and
        converts each source text into a separate ``user`` message.

        Returns
        -------
        dict
            Normalised payload ready for the downstream model.
        """
        options = GenerateQuestionFromTextsModel(**params)
        _payload = options.model_dump()

        self._map_prompt = {
            "##QUESTION_NUM_STR##": f"{_payload['number_of_questions']} question(s)",
        }

        _payload["model"] = _payload["model_name"]
        _payload["stream"] = _payload.get("stream", False)
        _payload["messages"] = [
            {
                "role": "user",
                "content": _t,
            }
            for _t in _payload["texts"]
        ]
        _payload.pop("texts")

        return _payload

    def __prepare_response_function(self, responses, contents):
        assert len(responses) == len(contents)

        questions = []
        for response, content in zip(responses, contents):
            _, _, dialog_question = self._get_choices_from_response(
                response=response
            )

            dialog_question = dialog_question.strip().split("\n\n")[-1]
            dialog_question = [q.strip() for q in dialog_question.split("\n")]
            questions.append(dialog_question)

        proper_texts_questions = self._prepare_proper_question_str(questions)
        gen_questions = self._prepare_response_for_generated_questions(
            texts=contents, proper_texts_questions=proper_texts_questions
        )

        return {
            "response": gen_questions,
            "generation_time": time.time() - self._start_time,
        }

    def _prepare_proper_question_str(
        self, questions: List[List[str]], split_with_question_mark: bool = False
    ) -> List[List[str]]:
        proper_texts_questions = []
        for text_questions in questions:
            new_text_questions = []
            for question in text_questions:
                text_q = question.strip()
                if not len(text_q):
                    continue
                if split_with_question_mark and "?" in text_q:
                    for spl_q in text_q.split("?"):
                        proper_q = self._remove_enumeration_from_question(spl_q)
                        proper_q = proper_q.strip()
                        if not len(proper_q):
                            continue
                        new_text_questions.append(proper_q + "?")
                else:
                    new_text_questions.append(
                        self._remove_enumeration_from_question(text_q)
                    )
            new_text_questions = [
                q.strip() for q in new_text_questions if len(q.strip())
            ]
            proper_texts_questions.append(new_text_questions)
        return proper_texts_questions

    @staticmethod
    def _remove_enumeration_from_question(question_str: str):
        question_str = question_str.strip()
        dot_pos = question_str.find(".")
        if dot_pos == -1:
            return question_str

        q_number = question_str[:dot_pos]
        try:
            _ = int(q_number)
            question_str = question_str[dot_pos + 1 :]
        except Exception:
            pass
        return question_str

    @staticmethod
    def _prepare_response_for_generated_questions(
        texts: List[str], proper_texts_questions: List[List[str]]
    ) -> List[Dict[str, List[List[str]]]]:
        response = []
        for txt, questions in zip(texts, proper_texts_questions):
            response_body = {"text": txt, "questions": questions}
            response.append(response_body)
        return response


class TranslateTexts(EndpointWithHttpRequestI):
    REQUIRED_ARGS = TRANSLATE_TEXT_REQ
    OPTIONAL_ARGS = TRANSLATE_TEXT_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/translate-to-pl",
        "en": "builtin/system/en/translate-to-pl",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "translate",
    ):
        super().__init__(
            ep_name=ep_name,
            api_types=["builtin"],
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            direct_return=False,
            call_for_each_user_msg=True,
        )

        self._prepare_response_function = self.__prepare_response_function

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:

        options = TranslateTextModel(**params)
        _payload = options.model_dump()
        _payload["stream"] = _payload.get("stream", False)
        _payload["model"] = _payload["model_name"]
        _payload["messages"] = [
            {
                "role": "user",
                "content": _t,
            }
            for _t in _payload["texts"]
        ]
        _payload.pop("texts")

        return _payload

    def __prepare_response_function(self, responses, contents):
        assert len(responses) == len(contents)

        translations = []
        for response, orig_text in zip(responses, contents):
            _, _, translated_to_pl = self._get_choices_from_response(
                response=response
            )
            translations.append(
                {
                    "original": orig_text,
                    "translated": translated_to_pl,
                }
            )

        return {
            "response": translations,
            "generation_time": time.time() - self._start_time,
        }


class SimplifyTexts(EndpointWithHttpRequestI):
    REQUIRED_ARGS = SIMPLIFY_TEXT_REQ
    OPTIONAL_ARGS = SIMPLIFY_TEXT_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/simplify-text",
        "en": "builtin/system/en/simplify-text",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "simplify_text",
    ):
        super().__init__(
            ep_name=ep_name,
            api_types=["builtin"],
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            direct_return=False,
            call_for_each_user_msg=True,
        )

        self._prepare_response_function = self.__prepare_response_function

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:

        options = SimplifyTextModel(**params)
        _payload = options.model_dump()
        _payload["model"] = _payload["model_name"]
        _payload["stream"] = _payload.get("stream", False)
        _payload["messages"] = [
            {
                "role": "user",
                "content": _t,
            }
            for _t in _payload["texts"]
        ]
        _payload.pop("texts")

        return _payload

    def __prepare_response_function(self, responses, contents):
        assert len(responses) == len(contents)

        simplifications = []
        for response, orig_text in zip(responses, contents):
            _, _, simpl_text = self._get_choices_from_response(response=response)
            simplifications.append(simpl_text)

        return {
            "response": simplifications,
            "generation_time": time.time() - self._start_time,
        }


class GenerateNewsFromTextHandler(EndpointWithHttpRequestI):
    REQUIRED_ARGS = GENERATE_ART_REQ
    OPTIONAL_ARGS = GENERATE_ART_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/news-on-sm",
        "en": "builtin/system/en/news-on-sm",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "generate_article_from_text",
    ):
        super().__init__(
            ep_name=ep_name,
            api_types=["builtin"],
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            direct_return=False,
            call_for_each_user_msg=False,
        )

        self._prepare_response_function = self.__prepare_response_function

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        options = GenerateArticleFromTextModel(**params)
        _payload = options.model_dump()
        _payload["stream"] = _payload.get("stream", False)
        _payload["model"] = _payload["model_name"]
        _payload["messages"] = [
            {
                "role": "user",
                "content": _payload["text"],
            },
        ]
        return _payload

    def __prepare_response_function(self, response):
        j_response, choices, assistant_response = self._get_choices_from_response(
            response=response
        )

        return {
            "response": {
                "article_text": choices[0].get("message", {}).get("content")
            },
            "generation_time": time.time() - self._start_time,
        }


class FullArticleFromTexts(GenerateNewsFromTextHandler):
    REQUIRED_ARGS = FULL_ARTICLE_REQ
    OPTIONAL_ARGS = FULL_ARTICLE_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/full-article",
        "en": "builtin/system/en/full-article",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "create_full_article_from_texts",
    ):
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
        )

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:

        options = CreateArticleFromNewsList(**params)
        _payload = options.model_dump()

        map_prompt = {
            "##USER_Q_STR##": _payload["user_query"],
        }
        prompt_str_postfix = _payload.get("article_type")

        user_texts_str = "\n\n".join(
            t.strip() for t in _payload["texts"] if len(t.strip())
        )

        _payload["stream"] = _payload.get("stream", False)
        _payload["model"] = _payload["model_name"]
        _payload["messages"] = [
            {
                "role": "user",
                "content": user_texts_str,
            }
        ]
        _payload.pop("texts")
        _payload.pop("user_query")
        _payload.pop("article_type")

        _payload["map_prompt"] = map_prompt
        _payload["prompt_str_postfix"] = prompt_str_postfix

        return _payload


class AnswerBasedOnTheContext(GenerateNewsFromTextHandler):
    REQUIRED_ARGS = CONTEXT_ANSWER_REQ
    OPTIONAL_ARGS = CONTEXT_ANSWER_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/answer-from-context-simple",
        "en": "builtin/system/en/answer-from-context-simple",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "generative_answer",
    ):
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
        )

        self._prepare_response_function = self.__prepare_response_function

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:

        options = AnswerBasedOnTheContextModel(**params)
        _payload = options.model_dump()
        _payload["stream"] = _payload.get("stream", False)
        _payload["model"] = _payload["model_name"]

        map_prompt = {
            "##QUESTION_STR##": _payload["question_str"],
        }
        prompt_str_postfix = _payload.get("question_prompt")
        prompt_str_force = _payload.get("system_prompt")

        context = ""
        if type(_payload["texts"]) is dict:
            doc_name_in_answer = _payload.get("doc_name_in_answer", False)
            for doc_name, tests in _payload["texts"].items():
                for t in tests:
                    if doc_name_in_answer:
                        t = f"Document name: {doc_name}\nDocument context: {t}"

                    context += t + "\n\n"
        elif type(_payload["texts"]) is list:
            for t in _payload["texts"]:
                context += t + "\n\n"

        _payload["messages"] = [
            {
                "role": "user",
                "content": context.strip(),
            }
        ]
        _payload.pop("texts")
        _payload.pop("question_str")
        _payload.pop("system_prompt")
        _payload.pop("question_prompt")

        _payload["map_prompt"] = map_prompt
        _payload["prompt_str_force"] = prompt_str_force
        _payload["prompt_str_postfix"] = prompt_str_postfix

        return _payload

    def __prepare_response_function(self, response):
        j_response, choices, assistant_response = self._get_choices_from_response(
            response=response
        )

        return {
            "response": choices[0].get("message", {}).get("content"),
            "generation_time": time.time() - self._start_time,
        }
