import time
from typing import Optional, Dict, Any, List

from rdl_ml_utils.handlers.prompt_handler import PromptHandler


from llm_proxy_rest.core.data_models.builtin_utils import (
    GenerateQuestionFromTexts,
    GENERATE_Q_REQ,
    GENERATE_Q_OPT,
    GenerateArticleFromText,
    GENERATE_ART_REQ,
    GENERATE_ART_OPT,
    TRANSLATE_TEXT_REQ,
    TRANSLATE_TEXT_OPT,
    TranslateTextModel,
)
from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.endpoint_i import EndpointWithHttpRequestI


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

    @EP.response_time
    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:

        options = GenerateQuestionFromTexts(**params)
        _payload = options.model_dump()

        self._map_prompt = {
            "##QUESTION_NUM_STR##": f"{_payload['number_of_questions']} question(s)",
        }

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
        options = GenerateArticleFromText(**params)
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

    @EP.response_time
    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:

        options = TranslateTextModel(**params)
        _payload = options.model_dump()
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
