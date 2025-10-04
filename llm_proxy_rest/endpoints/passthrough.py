"""
Passthrough endpoint interface.

This module defines :class:`PassthroughI`, an abstract base class that
provides a simple pass‑through implementation for LLM proxy REST
endpoints. It inherits from :class:`BaseEndpointInterface` and
implements a ``parametrize`` method that returns the provided parameters
unchanged. Subclasses can extend this class to add custom behavior
while retaining the basic request handling infrastructure.
"""

from abc import ABC
from typing import Optional, Dict, Any, List

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.endpoint_i import BaseEndpointInterface


class PassthroughI(BaseEndpointInterface, ABC):
    """
    Abstract base class for a pass‑through REST endpoint.

    The class does not enforce any required or optional arguments
    (``REQUIRED_ARGS`` and ``OPTIONAL_ARGS`` are ``None``) and does not
    specify a system prompt name. It primarily forwards incoming request
    parameters without modification.

    Subclasses should implement any additional processing logic as
    needed.
    """

    REQUIRED_ARGS = None
    OPTIONAL_ARGS = None
    SYSTEM_PROMPT_NAME = None

    def __init__(
        self,
        logger_file_name: Optional[str],
        logger_level: Optional[str],
        model_handler: Optional[ModelHandler],
        prompt_handler: Optional[PromptHandler],
        ep_name: str,
        method: str,
        api_types: List[str],
        dont_add_api_prefix: bool,
        redirect_ep: bool,
    ):
        """
        Initialize the pass‑through endpoint.

        Args:
            logger_file_name: Optional path to a file for logging output.
            logger_level: Logging level, defaults to ``REST_API_LOG_LEVEL``.
            model_handler: Optional :class:`ModelHandler` instance.
            prompt_handler: Optional :class:`PromptHandler` instance.
            ep_name: Name of the endpoint, used for routing and logging.
            method: HTTP method for the endpoint, default ``"POST"``.
            dont_add_api_prefix: If ``True``, the endpoint will not be
                prefixed with the API base path.
            redirect_ep: If ``True``, the endpoint will redirected to api host.
        """
        super().__init__(
            ep_name=ep_name,
            api_types=api_types,
            method=method,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=dont_add_api_prefix,
            redirect_ep=redirect_ep,
        )

    @EP.response_time
    def parametrize(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Return the incoming parameters unchanged.

        This method can be overridden by subclasses to modify or
        validate request parameters before they are processed further.

        Args:
            params: Dictionary of request parameters or ``None``.

        Returns:
            The original ``params`` dictionary, or an empty ``dict`` if
            ``params`` is ``None``.
        """
        return params or {}
