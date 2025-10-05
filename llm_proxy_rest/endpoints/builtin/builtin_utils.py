import time
from typing import Optional, Dict, Any

from rdl_ml_utils.handlers.prompt_handler import PromptHandler


from llm_proxy_rest.core.data_models.builtin_utils import (
    GenerateQuestionFromTexts,
    GENERATE_Q_REQ,
    GENERATE_Q_OPT,
    GenerateArticleFromText,
    GENERATE_ART_REQ,
    GENERATE_ART_OPT,
)
from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.endpoint_i import EndpointWithHttpRequestI

#
#
# class GenerateQuestionsFromTexts(EndpointWithHttpRequestI):
#     REQUIRED_ARGS = GENERATE_Q_REQ
#     OPTIONAL_ARGS = GENERATE_Q_OPT
#     SYSTEM_PROMPT_NAME = {
#         "pl": "builtin/system/pl/generate-questions",
#         "en": "builtin/system/en/generate-questions",
#     }
#
#     def __init__(
#         self,
#         logger_file_name: Optional[str] = None,
#         logger_level: Optional[str] = REST_API_LOG_LEVEL,
#         prompt_handler: Optional[PromptHandler] = None,
#         model_handler: Optional[ModelHandler] = None,
#         ep_name: str = "generate_questions",
#     ):
#         super().__init__(
#             ep_name=ep_name,
#             api_types=["builtin"],
#             method="POST",
#             logger_level=logger_level,
#             logger_file_name=logger_file_name,
#             prompt_handler=prompt_handler,
#             model_handler=model_handler,
#             dont_add_api_prefix=False,
#             direct_return=False,
#             call_for_each_user_msg=True,
#         )
#
#     @EP.response_time
#     @EP.require_params
#     def prepare_payload(
#         self, params: Optional[Dict[str, Any]]
#     ) -> Optional[Dict[str, Any]]:
#
#         options = GenerateQuestionFromTexts(**params)
#         _payload = options.model_dump()
#
#         self._map_prompt = {
#             "##QUESTION_NUM_STR##",
#             str(options["number_of_questions"]) + "question(s)",
#         }
#
#         _payload["model"] = _payload["model_name"]
#         _payload["messages"] = [
#             {
#                 "role": "user",
#                 "content": _payload["user_last_statement"],
#             },
#         ] + _payload["historical_messages"]
#         return _payload


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
