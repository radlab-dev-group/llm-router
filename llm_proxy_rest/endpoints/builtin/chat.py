from pydantic import ValidationError
from typing import Optional, Dict, Any

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.endpoint_i import BaseEndpointInterface
from llm_proxy_rest.endpoints.data_models.genai import (
    GenerativeConversationModel,
    ExtendedGenerativeConversationModel,
    GENAI_CONV_REQ_ARGS,
    GENAI_CONV_OPT_ARGS,
    EXT_GENAI_CONV_REQ_ARGS,
    EXT_GENAI_CONV_OPT_ARGS,
)


class ConversationWithModel(BaseEndpointInterface):
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
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
        )

    @EP.response_time
    @EP.require_params
    def parametrize(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        try:
            options = GenerativeConversationModel(**params)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        return options.model_dump()


class ExtendedConversationWithModel(BaseEndpointInterface):
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
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
        )

    @EP.response_time
    @EP.require_params
    def parametrize(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        try:
            options = ExtendedGenerativeConversationModel(**params)
        except ValidationError as exc:
            raise ValueError(str(exc)) from exc
        return options.model_dump()


class OpenAPIChat(ExtendedConversationWithModel):
    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name="chat",
    ):
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
        )


#
# class OpenAPICompletion(ExtendedConversationWithModel):
#     def __init__(
#         self,
#         logger_file_name: Optional[str] = None,
#         logger_level: Optional[str] = REST_API_LOG_LEVEL,
#         prompt_handler: Optional[PromptHandler] = None,
#         ep_name="completion",
#     ):
#         super().__init__(
#             ep_name=ep_name,
#             logger_level=logger_level,
#             logger_file_name=logger_file_name,
#             prompt_handler=prompt_handler,
#         )
