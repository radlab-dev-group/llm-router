"""
llm_proxy_rest.endpoints.builtin.lmstudio
==========================================

Endpoint implementations for the **LM Studio** provider.  The module defines
separate endpoint classes for model listing, chat, and text generation, as
well as a concrete :class:`LmStudioType` that implements the
:class:`~llm_proxy_rest.core.api_types.ApiTypesI` interface for LM Studio.

All endpoint classes inherit from :class:`EndpointWithHttpRequestI`,
a ``prepare_payload`` implementation, and the appropriate HTTP method configuration.
"""

from typing import Optional

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.builtin.openai import OpenAIModelsHandler


class LmStudioModelsHandler(OpenAIModelsHandler):
    """
    Endpoint that returns the list of model identifiers available in the
    LM Studio service.

    The endpoint is registered under the name ``models`` and supports the
    HTTP ``GET`` method.  No request parameters are required; the response
    contains a ``models`` key with a list of model IDs.
    """

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "v0/models",
    ):
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            api_types=["lmstudio"],
        )
