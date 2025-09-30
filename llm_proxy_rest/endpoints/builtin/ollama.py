from typing import Optional, Dict, Any

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.endpoint_i import BaseEndpointInterface


class OllamaHome(BaseEndpointInterface):
    """
    Health‑check endpoint that returns a simple *pong* response.

    This endpoint is registered under the name ``ping`` and only supports
    the HTTP ``GET`` method.  It does not require any request parameters
    and is typically used by monitoring tools to verify that the service
    is up and responding.

    Attributes:
        REQUIRED_ARGS (list): Empty list – no required arguments.
        OPTIONAL_ARGS (list): Empty list – no optional arguments.
    """

    REQUIRED_ARGS = []
    OPTIONAL_ARGS = []
    SYSTEM_PROMPT_NAME = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "/",
    ):
        """
        Create a ``Ping`` endpoint instance.

        Args:
            logger_file_name: Optional logger file name.
                If not given, then a default logger file name will be used.
            logger_level: Optional logger level. Defaults to ``REST_API_LOG_LEVEL``.
            prompt_handler: Optional prompt handler instance. Defaults to ``None``.
        """
        super().__init__(
            method="GET",
            ep_name=ep_name,
            logger_file_name=logger_file_name,
            logger_level=logger_level,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=True,
        )

    @EP.response_time
    def parametrize(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any] | str]:
        """Execute the endpoint logic.

        Args:
            params: Optional dictionary of query parameters.
                The ping endpoint ignores any supplied parameters.

        Returns:
            dict: A response dictionary containing the string ``"pong"``,
            generated via ``return_response_ok``.
        """
        self.direct_return = True
        return "Ollama is running"


class OllamaTags(BaseEndpointInterface):
    REQUIRED_ARGS = []
    OPTIONAL_ARGS = []
    SYSTEM_PROMPT_NAME = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "tags",
        dont_add_api_prefix=False,
    ):
        super().__init__(
            ep_name=ep_name,
            method="GET",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=dont_add_api_prefix,
        )

    @EP.response_time
    @EP.require_params
    def parametrize(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        self.direct_return = True
        return {
            "models": self._api_type_dispatcher.tags(
                models_config=self._model_handler.list_active_models(),
                merge_to_list=True,
            )
        }
