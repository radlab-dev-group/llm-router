"""
vLLM endpoint implementation.

This module provides a concrete endpoint class that adapts the generic
``OpenAIResponseHandler`` to the *vLLM* backend.  It wires together logging,
prompt handling, and model resolution so that a Flask route can expose the
``/v1/chat/completions`` OpenAI‑compatible API while delegating the actual
generation to a locally‑hosted vLLM model server.
"""

from typing import Optional

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_api.core.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.endpoints.builtin.openai import OpenAIResponseHandler


class VllmChatCompletion(OpenAIResponseHandler):
    """
    OpenAI‑compatible chat endpoint backed by a vLLM model.

    The class inherits the full request‑validation, guard‑rail, and response‑
    handling logic from :class:`OpenAIResponseHandler`.  It only overrides the
    constructor to configure the endpoint name, supported API type, and the
    optional prompt/model handlers.

    Class attributes
    ----------------
    REQUIRED_ARGS : None
        vLLM does not enforce any mandatory request parameters beyond those
        already validated by the base class.
    OPTIONAL_ARGS : None
        No additional optional arguments are defined for this endpoint.
    SYSTEM_PROMPT_NAME : None
        System‑prompt injection is delegated to the base handler; this endpoint
        does not define a specific prompt name.
    """

    REQUIRED_ARGS = None
    OPTIONAL_ARGS = None
    SYSTEM_PROMPT_NAME = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[ModelHandler] = None,
        model_handler: Optional[PromptHandler] = None,
        ep_name="/v1/chat/completions",
        method="POST",
        dont_add_api_prefix: bool = True,
    ):
        """
        Initialize the OpenAI chat endpoint.

        Parameters
        ----------
        logger_file_name : Optional[str]
            Log file name; defaults to the library’s standard configuration.
        logger_level : Optional[str]
            Logging level; defaults to :data:`REST_API_LOG_LEVEL`.
        prompt_handler : Optional[ModelHandler]
            Handler for prompt templates (passed through to the backend).
        model_handler : Optional[PromptHandler]
            Handler for model configuration.
        ep_name : str
            Endpoint name; defaults to ``"chat"``.
        method : str
            HTTP method to use; defaults to ``"POST"``.
        dont_add_api_prefix : bool
            If ``True`` the global API prefix is omitted.
        """
        super().__init__(
            ep_name=ep_name,
            api_types=["vllm"],
            method=method,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=dont_add_api_prefix,
            direct_return=False,
        )

        self._prepare_response_function = self.prepare_response_function
