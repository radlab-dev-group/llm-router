"""
llm_router_api.endpoints.builtin.builtin_health
================================================

Built‑in health endpoint exposed by the REST API.  The module provides a
single endpoint class, :class:`Health`, which implements a simple ``GET``
request that confirms the service is up and responds with a ``200 OK``
status.

The endpoint is intended for load balancers and orchestrators
(e.g. Kubernetes liveness/readiness probes, Docker health checks) and does
not require any request parameters or authentication.
"""

from typing import Any, Dict, Optional

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_api.core.decorators import EP
from llm_router_api.core.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.endpoints.endpoint_i import EndpointWithHttpRequestI


class Health(EndpointWithHttpRequestI):
    """
    Health endpoint that returns an HTTP ``200 OK`` response.

    Registered at ``/health`` (no global API prefix, i.e. ``dont_add_api_prefix=True``).
    Auth: **public** — added to the default ``LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS``
    list, so it never requires a token even when authentication is enabled.

    This endpoint is a lightweight liveness/readiness probe.  It requires no
    request parameters and always responds with a ``200`` status code and a
    small JSON body produced via :meth:`EndpointWithHttpRequestI.return_response_ok`.

    Attributes:
        REQUIRED_ARGS (list): Empty list – no required arguments.
        OPTIONAL_ARGS (list): Empty list – no optional arguments.
        SYSTEM_PROMPT_NAME (dict): Not set - as None
    """

    EP_DONT_NEED_GUARDRAIL_AND_MASKING = True

    REQUIRED_ARGS = []
    OPTIONAL_ARGS = []
    SYSTEM_PROMPT_NAME = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "health",
        dont_add_api_prefix: bool = True,
    ):
        """
        Initialize the ``Health`` endpoint.

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
            Endpoint name used for routing; defaults to ``"health"``.
        dont_add_api_prefix : bool
            When ``True`` the global API prefix is not added to the route
            (default ``True`` so the endpoint is served at ``/health``).
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
            direct_return=True,
        )

    @EP.response_time
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Execute the health‑check logic.

        Parameters
        ----------
        params : Optional[Dict[str, Any]]
            Ignored – the endpoint does not use request parameters.

        Returns
        -------
        Dict
            A response dictionary produced via
            :meth:`EndpointWithHttpRequestI.return_response_ok`, which the
            Flask registrar serialises with an HTTP ``200`` status code.
        """
        return self.return_response_ok("healthy")
