"""
Service interface for built‑in HTTP endpoints.

Provides a reusable base class that handles:

* POST and GET requests to a specific endpoint,
* JSON response parsing with error translation into :class:`LLMRouterError`,
* configurable request retry via :class:`~llm_router_lib.utils.http.HttpRequester`.

Concrete service classes (e.g. ``ConversationWithModelService``,
``PingService``) extend this
base class and bind an ``endpoint`` URL and a ``model_cls`` (Pydantic model for
payload validation).
"""

import abc
import logging

from typing import Any, Dict, Optional

from llm_router_lib.exceptions import LLMRouterError
from llm_router_lib.utils.http import HttpRequester


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

    # Pydantic model class used to validate
    # the request payload (None for GET endpoints).
    model_cls: Optional[type] = None

    def __init__(self, http: HttpRequester, logger: Optional[logging.Logger] = None):
        """
        Initialise the service wrapper.

        Parameters
        ----------
        http : HttpRequester
            Helper object that knows how to perform HTTP requests.
        logger : Optional[logging.Logger]
            Logger instance used for debugging and error reporting.
        """
        self.http = http
        self.logger = logger

    # ------------------------------------------------------------------ #
    # JSON parsing helper (DRY: shared by call_post / call_get)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_json_response(resp) -> Dict[str, Any]:
        """Parse a requests.Response as JSON, raising LLMRouterError on failure."""
        try:
            return resp.json()
        except ValueError as inner_exc:
            raise LLMRouterError(
                f"Invalid JSON response from {resp.url}: {inner_exc}"
            ) from inner_exc

    # ------------------------------------------------------------------ #
    def call_post(self, raw_payload: Any) -> Dict[str, Any]:
        """
        Send a POST request to the configured endpoint and return the JSON body.

        The method does not perform payload validation itself; callers are
        expected to instantiate ``raw_payload`` using ``self.model_cls`` before
        invoking this method.  If the HTTP response cannot be parsed as JSON, a
        ``LLMRouterError`` is raised to surface the problem to higher layers.

        Parameters
        ----------
        raw_payload : Any
            The request body, typically an instance of ``self.model_cls`` or a
            dictionary produced by its ``model_dump()`` method.

        Returns
        -------
        Dict
            The parsed JSON response from the backend service.

        Raises
        ------
        LLMRouterError
            If the response body cannot be decoded as JSON.
        """
        resp = self.http.post(self.endpoint, json=raw_payload)
        return self._parse_json_response(resp)

    # ------------------------------------------------------------------ #
    def call_get(self, raw_payload: Optional[Any] = None) -> Dict[str, Any]:
        """
        Send a GET request to the configured endpoint and return the JSON body.

        The method does not perform payload validation itself; callers are
        expected to instantiate ``raw_payload`` using ``self.model_cls`` before
        invoking this method.  If the HTTP response cannot be parsed as JSON, a
        ``LLMRouterError`` is raised to surface the problem to higher layers.

        Parameters
        ----------
        raw_payload : Optional[Any]
            Optional request body, typically an instance of ``self.model_cls``
            or a dictionary produced by its ``model_dump()`` method.

        Returns
        -------
        Dict
            The parsed JSON response from the backend service.

        Raises
        ------
        LLMRouterError
            If the response body cannot be decoded as JSON.
        """
        resp = self.http.get(self.endpoint, json=raw_payload)
        return self._parse_json_response(resp)
