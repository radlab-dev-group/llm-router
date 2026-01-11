"""
Anthropic-specific endpoint implementations.
"""

from typing import Optional, Dict, Any, List

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_api.core.decorators import EP
from llm_router_api.core.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.endpoints.passthrough import PassthroughI
from llm_router_api.core.api_types.anthropic import AnthropicConverters


class AnthropicChatHandler(PassthroughI):
    """
    Handler for Anthropic Messages API.
    """

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name="messages",
        method="POST",
        dont_add_api_prefix: bool = False,
        api_types: Optional[List[str]] = None,
        direct_return: bool = False,
    ):
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=dont_add_api_prefix,
            api_types=api_types or ["anthropic"],
            direct_return=direct_return,
            method=method,
        )

        self._prepare_response_function = self.prepare_response_function

    @EP.response_time
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Return the incoming parameters unchanged.
        """
        return params or {}

    @staticmethod
    def prepare_response_function(response):
        """
        Convert response to OpenAI-compatible format if it's already Anthropic,
        OR convert to Anthropic format if it's OpenAI/Ollama (reverse proxy case).
        """
        resp_json = response.json()

        if "message" in resp_json:
            return AnthropicConverters.FromOllama.convert_response(resp_json)
        if "choices" in resp_json:
            return AnthropicConverters.FromOpenAI.convert_response(resp_json)

        return resp_json
