from typing import Optional, Dict, Any, List

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.passthrough import PassthroughI


class VllmChatCompletion(PassthroughI):
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
