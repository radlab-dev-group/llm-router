"""
llm_proxy_rest.endpoints.builtin.ollama
========================================

Implementation of the Ollama provider endpoints and API type.  The module
contains three public classes:

* :class:`OllamaTags` – endpoint that returns the list of model tags.
* :class:`OllamaHome` – simple health‑check endpoint (``/``) used by
  monitoring tools.
* :class:`OllamaType` – concrete implementation of the :class:`ApiTypesI`
  interface that defines Ollama‑specific URL paths and request payload
  conversion logic.
"""

from typing import Optional, Dict, Any, List

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.endpoint_i import BaseEndpointInterface


class OllamaHome(BaseEndpointInterface):
    """
    Endpoint that returns a list of available model tags from the Ollama
    service.

    The endpoint is registered under the name ``tags`` and supports the HTTP
    ``GET`` method.  No request parameters are required; the response
    contains a ``models`` key with a list of model identifiers.

    Attributes
    ----------
    REQUIRED_ARGS : list
        Empty – the endpoint does not require positional arguments.
    OPTIONAL_ARGS : list
        Empty – the endpoint does not accept optional arguments.
    SYSTEM_PROMPT_NAME : None
        No system prompt is used for this endpoint.
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
            api_types=["ollama"],
        )

    @EP.response_time
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any] | str]:
        """
        Execute the health‑check logic.

        Parameters
        ----------
        params : Optional[Dict[str, Any]]
            Ignored – the endpoint does not process query parameters.

        Returns
        -------
        str
            The string ``\"Ollama is running\"`` indicating
            the successful health check.
        """
        self.direct_return = True
        return "Ollama is running"


class OllamaTags(BaseEndpointInterface):
    """
    Health‑check endpoint that returns a plain text confirmation that the
    Ollama service is running.

    The endpoint is registered under the root path ``/`` and only supports
    the HTTP ``GET`` method.  It does not require any request parameters.
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
            api_types=["ollama"],
        )

    @EP.response_time
    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        self.direct_return = True
        return {
            "models": self._api_type_dispatcher.tags(
                models_config=self._model_handler.list_active_models(),
                merge_to_list=True,
            )
        }
