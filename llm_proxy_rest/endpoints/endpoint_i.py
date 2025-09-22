"""
Module defining abstract base classes for API endpoints.

This module provides two abstract base classes:
    * `EndpointI` – the minimal interface required for any endpoint,
      handling URL registration, HTTP method validation, and a helper for
      successful responses.

    * `EndpointRequestCallI` – extends `EndpointI` with
      request‑parameter validation and concrete implementations for
      performing ``GET`` and ``POST`` calls using the `requests`
      library.

Both classes are intended to be subclassed by concrete endpoint
implementations in the ``llm_proxy_rest.endpoints`` package.
"""

import abc
import json
import requests

from typing import Dict, Any, Optional

from rdl_ml_utils.utils.logger import prepare_logger


class EndpointI(abc.ABC):
    """
    Abstract base class for a generic API endpoint.

    Attributes
    ----------
    _ep_name: str
        The relative URL path of the endpoint (e.g., ``"api/ping"``).
    _ep_method: str
        HTTP method used for the endpoint (``"GET"`` or ``"POST"``).
    logger: logging.Logger
        instance scoped to the module name.

    Subclasses must implement `call` and `_prepare_ep`.
    """

    METHODS = ["GET", "POST"]

    REQUIRED_ARGS = []
    OPTIONAL_ARGS = []

    def __init__(
        self,
        ep_name: str,
        method: str = "POST",
        logger_file_name: Optional[str] = None,
    ):
        """
        Create a new endpoint instance.

        Parameters
        ----------
        ep_name: str
            The endpoint's URL path.
        method: str, optional
            HTTP method to be used; defaults to ``"POST"``. Must be one
            of the values listed in `METHODS`.
        """
        self._ep_name = ep_name
        self._ep_method = method
        self.logger = prepare_logger(
            logger_name=__name__,
            logger_file_name=logger_file_name or "llm-proxy-rest.log",
        )

        self._check_method_is_allowed(method=method)
        self.prepare_ep()

    @property
    def name(self):
        return self._ep_name

    @property
    def method(self):
        return self._ep_method

    @abc.abstractmethod
    def call(self, params: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Execute the endpoint logic.

        Parameters
        ----------
        params: dict or None
            Parameters supplied by the caller. Concrete implementations
            may define required/optional keys.

        Returns
        -------
        dict or None
            The endpoint's response payload, or ``None`` if no content
            should be returned.
        """
        raise NotImplementedError()

    def prepare_ep(self):
        """
        Perform any endpoint‑specific preparation.

        This hook is called during initialization and can be used to
        validate configuration, preload resources, etc.
        """
        ...

    @staticmethod
    def return_response_ok(body: Any) -> Dict[str, Any]:
        """
        Construct a standard successful response payload.

        Parameters
        ----------
        body: Any
            The content to be wrapped in the response.

        Returns
        -------
        dict
            Dictionary with ``"status": True`` and the provided ``body``.
        """
        return {"status": True, "body": body}

    @staticmethod
    def return_response_not_ok(body: Optional[Any]) -> Dict[str, Any]:
        """
        Construct a standard error response payload.

        Parameters
        ----------
        body: Any
            The error details or message to be wrapped in the response.

        Returns
        -------
        dict
            Dictionary with ``"status": False`` and the provided ``body``.
        """
        if body is None or not len(body):
            return {"status": False}
        return {"status": False, "body": body}

    def check_required_params(self, params: Optional[Dict[str, Any]]) -> None:
        """
        Ensure all required arguments are present in *params*.

        Raises
        ------
        ValueError
            If any argument listed in `REQUIRED_ARGS` is missing.
        """
        if (
            params is None
            or self.REQUIRED_ARGS is None
            or not len(self.REQUIRED_ARGS)
        ):
            return

        missing = [arg for arg in self.REQUIRED_ARGS if arg not in params]
        if missing:
            raise ValueError(
                f"Missing required argument(s) {missing} for endpoint {self._ep_name}"
            )

    def filter_allowed_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Remove keys that are not declared as required or optional.

        Unknown keys generate a warning via the instance logger.

        Returns
        -------
        dict
            A new dictionary containing only allowed parameters.
        """
        allowed = set(self.REQUIRED_ARGS or []) | set(self.OPTIONAL_ARGS or [])
        unknown = [k for k in params if k not in allowed]
        if unknown:
            self.logger.warning(
                f"Ignoring unknown argument(s) {unknown} for endpoint {self._ep_name}",
            )
            filtered_params = {k: v for k, v in params.items() if k in allowed}
        else:
            filtered_params = params
        return filtered_params

    def _check_method_is_allowed(self, method: str) -> None:
        """
        Validate that *method* is permitted for this endpoint.

        Raises
        ------
        ValueError
            If *method* is not present in `METHODS`.
        """
        if method not in self.METHODS:
            _m_str = ", ".join(self.METHODS)
            raise ValueError(
                f"Unknown method {method}. Method must be one of {_m_str}"
            )


class EndpointWithHttpRequestI(EndpointI, abc.ABC):
    """
    Abstract endpoint that performs HTTP requests to an external service.

    Extends `EndpointI` with logic for:
    * Validating required and optional parameters.
    * Filtering out unknown parameters.
    * Dispatching ``GET`` or ``POST`` requests via `requests`.
    """

    def __init__(self, ep_name: str, method: str = "GET", timeout: int = 30):
        super().__init__(ep_name=ep_name, method=method)

        self._timeout = timeout

    def _call_http_request(self, params: Dict[str, Any]) -> Optional[Dict]:
        """
        Internal helper that validates parameters and executes the request.

        Parameters
        ----------
        params: dict
            Dictionary of request parameters supplied by the caller.

        Returns
        -------
        dict or None
            Parsed JSON response from the external service, or a dictionary
            containing the raw text if JSON decoding fails.
        """
        params = self.filter_allowed_params(params=params)

        if self._ep_method == "POST":
            return self._call_post_with_payload(params)
        return self._call_get_with_payload(params)

    def _call_post_with_payload(self, params: Dict[str, Any]) -> Optional[Dict]:
        """
        Perform a POST request to ``self.ep_url`` with a JSON body.

        Parameters
        ----------
        params: dict
            Payload to be JSON‑encoded and sent in the request body.

        Returns
        -------
        dict or None
            The decoded JSON response, or a ``{'raw_response': ...}`` dict
            if the response is not valid JSON.

        Raises
        ------
        RuntimeError
            If the request fails or the response status indicates an error.
        """
        try:
            response = requests.post(
                self._ep_name, json=params, timeout=self._timeout
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"POST request to {self._ep_name} failed: {exc}"
            ) from exc
        return self.__return_http_response(response=response)

    def _call_get_with_payload(self, params: Dict[str, Any]) -> Optional[Dict]:
        """
        Perform a GET request to ``self.ep_url`` using *params* as a query string.

        Parameters
        ----------
        params: dict
            Query‑string parameters for the GET request.

        Returns
        -------
        dict or None
            The decoded JSON response, or a ``{'raw_response': ...}`` dict
            if the response is not valid JSON.

        Raises
        ------
        RuntimeError
            If the request fails or the response status indicates an error.
        """
        try:
            response = requests.get(
                self._ep_name, params=params, timeout=self._timeout
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"GET request to {self._ep_name} failed: {exc}"
            ) from exc
        return self.__return_http_response(response=response)

    def __return_http_response(self, response):
        if not response.ok:
            raise RuntimeError(
                f"POST request to {self._ep_name} returned status "
                f"{response.status_code}: {response.text}"
            )
        try:
            return response.json()
        except json.JSONDecodeError:
            return {"raw_response": response.text}
