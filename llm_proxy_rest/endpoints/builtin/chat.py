from pydantic import ValidationError
from typing import Optional, Dict, Any

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.endpoints.endpoint_i import EndpointI
from llm_proxy_rest.endpoints.data_models.genai import (
    GenerativeConversationModel,
    ExtendedGenerativeConversationModel,
    GENAI_CONV_REQ_ARGS,
    GENAI_CONV_OPT_ARGS,
    EXT_GENAI_CONV_REQ_ARGS,
    EXT_GENAI_CONV_OPT_ARGS,
)


class ConversationWithModel(EndpointI):
    REQUIRED_ARGS = GENAI_CONV_REQ_ARGS
    OPTIONAL_ARGS = GENAI_CONV_OPT_ARGS
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/chat-conversation-simple",
        "en": "builtin/system/en/chat-conversation-simple",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = "DEBUG",
        prompt_handler: Optional[PromptHandler] = None,
    ):
        super().__init__(
            ep_name="conversation_with_model",
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
        )

    @EP.require_params
    def call(self, params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        try:
            options = GenerativeConversationModel(**params)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

        return self.return_response_ok(options.model_dump())


class ExtendedConversationWithModel(EndpointI):
    REQUIRED_ARGS = EXT_GENAI_CONV_REQ_ARGS
    OPTIONAL_ARGS = EXT_GENAI_CONV_OPT_ARGS
    SYSTEM_PROMPT_NAME = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = "DEBUG",
        prompt_handler: Optional[PromptHandler] = None,
    ):
        super().__init__(
            ep_name="extended_conversation_with_model",
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
        )

    @EP.require_params
    def call(self, params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        try:
            options = ExtendedGenerativeConversationModel(**params)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc

        return self.return_response_ok(options.model_dump())
