import abc
from typing import Dict, Any, Type

from llm_router_lib.utils.http import HttpRequester
from llm_router_lib.exceptions import LLMRouterError


class BaseConversationServiceInterface(abc.ABC):
    """
    Abstract base class for conversation‑service wrappers.

    Sub‑classes must set the ``endpoint`` attribute (the relative URL to which
    the request is sent) and the ``model_cls`` attribute (the Pydantic model
    used for payload validation).  The class provides a reusable ``call``
    method that performs the HTTP POST and returns a parsed JSON dictionary,
    raising a domain‑specific ``LLMRouterError`` when the response cannot be
    decoded.
    """

    # Relative URL of the endpoint to call
    endpoint: str = ""

    # Pydantic model class used to validate the request payload.
    model_cls: Type[Any] = None

    def __init__(self, http: HttpRequester, logger):
        """
        Initialise the service wrapper.

        Parameters
        ----------
        http : HttpRequester
            Helper object that knows how to perform HTTP requests.
        logger : logging.Logger
            Logger instance used for debugging and error reporting.
        """
        self.http = http
        self.logger = logger

    def call(self, raw_payload: Any) -> Dict[str, Any]:
        """
        Send a POST request to the configured endpoint and return the JSON body.

        The method does not perform payload validation itself; callers are
        expected to instantiate ``raw_payload`` using ``self.model_cls`` before
        invoking ``call``.  If the HTTP response cannot be parsed as JSON, a
        ``LLMRouterError`` is raised to surface the problem to higher layers.

        Parameters
        ----------
        raw_payload : Any
            The request body, typically an instance of ``self.model_cls`` or a
            dictionary produced by its ``model_dump`` method.

        Returns
        -------
        dict
            The parsed JSON response from the backend service.

        Raises
        ------
        LLMRouterError
            If the response body cannot be decoded as JSON.
        """
        resp = self.http.post(self.endpoint, json=raw_payload)
        try:
            j = resp.json()
        except Exception as exc:
            raise LLMRouterError(f"Invalid response format: {exc}")
        return j
