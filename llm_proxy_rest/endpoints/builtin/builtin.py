"""
llm_proxy_rest.endpoints.builtin.builtin
================================================

Built‑in health‑check endpoint used by the REST API.  The module currently
exposes a single endpoint class, :class:`Ping`, which implements a simple
``GET`` request that returns a *pong* response.  The endpoint is useful for
monitoring and for confirming that the service is reachable.
"""

from typing import Optional, Dict, Any, List

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_proxy_rest.core.decorators import EP
from llm_proxy_rest.base.model_handler import ModelHandler
from llm_proxy_rest.base.constants import REST_API_LOG_LEVEL
from llm_proxy_rest.endpoints.endpoint_i import BaseEndpointInterface


class Ping(BaseEndpointInterface):
    """
    Health‑check endpoint that returns a simple *pong* response.

    This endpoint is registered under the name ``ping`` and only supports
    the HTTP ``GET`` method.  It does not require any request parameters
    and is typically used by monitoring tools to verify that the service
    is up and responding.

    Attributes:
        REQUIRED_ARGS (list): Empty list – no required arguments.
        OPTIONAL_ARGS (list): Empty list – no optional arguments.
        SYSTEM_PROMPT_NAME (dict): Not set - as None
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
        ep_name: str = "ping",
        dont_add_api_prefix: bool = False,
    ):
        """
        Initialize the ``Ping`` endpoint.

        Parameters
        ----------
        logger_file_name : Optional[str]
            Name of the log file; if omitted a default logger configuration is used.
        logger_level : Optional[str]
            Logging level; defaults to :data:`REST_API_LOG_LEVEL`.
        model_handler : Optional[ModelHandler]
            Model handler instance (unused by this endpoint).
        prompt_handler : Optional[PromptHandler]
            Prompt handler instance (unused by this endpoint).
        ep_name : str
            Endpoint name used for routing; defaults to ``"ping"``.
        dont_add_api_prefix : bool
            When ``True`` the global API prefix is not added to the route.
        """
        super().__init__(
            method="GET",
            ep_name=ep_name,
            logger_file_name=logger_file_name,
            logger_level=logger_level,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=dont_add_api_prefix,
            api_types=["builtin"],
        )

    @EP.response_time
    def parametrize(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Execute the health‑check logic.

        Parameters
        ----------
        params : Optional[Dict[str, Any]]
            Ignored – the endpoint does not use query parameters.

        Returns
        -------
        dict
            A response dictionary with the key ``"pong"`` produced via
            :meth:`BaseEndpointInterface.return_response_ok`.
        """
        self.direct_return = True
        return self.return_response_ok("pong")
