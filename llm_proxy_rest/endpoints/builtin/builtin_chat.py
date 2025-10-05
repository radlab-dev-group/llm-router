import time
from typing import Optional, Dict, Any

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.core.data_models.builtin_chat import (
    GENAI_CONV_REQ_ARGS,
    GENAI_CONV_OPT_ARGS,
    GenerativeConversationModel,
    EXT_GENAI_CONV_REQ_ARGS,
    EXT_GENAI_CONV_OPT_ARGS,
    ExtendedGenerativeConversationModel,
)
from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.endpoint_i import EndpointWithHttpRequestI


class ConversationWithModel(EndpointWithHttpRequestI):
    REQUIRED_ARGS = GENAI_CONV_REQ_ARGS
    OPTIONAL_ARGS = GENAI_CONV_OPT_ARGS
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/chat-conversation-simple",
        "en": "builtin/system/en/chat-conversation-simple",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "conversation_with_model",
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
        )

        self._prepare_response_function = self.__prepare_response_function

    @EP.response_time
    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        options = GenerativeConversationModel(**params)
        _payload = options.model_dump()
        _payload["model"] = _payload["model_name"]
        _payload["messages"] = [
            {
                "role": "user",
                "content": _payload["user_last_statement"],
            },
        ] + _payload["historical_messages"]

        return _payload

    def __prepare_response_function(self, response):
        j_response, choices, assistant_response = self._get_choices_from_response(
            response=response
        )

        return {
            "response": assistant_response,
            "generation_time": time.time() - self._start_time,
        }


class ExtendedConversationWithModel(ConversationWithModel):
    REQUIRED_ARGS = EXT_GENAI_CONV_REQ_ARGS
    OPTIONAL_ARGS = EXT_GENAI_CONV_OPT_ARGS
    SYSTEM_PROMPT_NAME = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "extended_conversation_with_model",
    ):
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
        )

    @EP.response_time
    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        options = ExtendedGenerativeConversationModel(**params)
        _payload = options.model_dump()
        _payload["model"] = _payload["model_name"]
        _payload["messages"] = [
            {
                "role": "system",
                "content": _payload["system_prompt"],
            },
            {
                "role": "user",
                "content": _payload["user_last_statement"],
            },
        ] + _payload["historical_messages"]
        return _payload
