"""
Thin wrapper around ``requests`` that adds logging,
retries and unified error handling.

The :class:`HttpRequester` class is used throughout the library to communicate
with downstream services (e.g. model providers, auxiliary APIs).  It centralises:

* construction of absolute URLs from a base URL,
* automatic inclusion of a bearer token,
* a configurable retry policy via ``urllib3.Retry``,
* conversion of HTTP error codes into the library‑specific exception hierarchy
  (:class:`AuthenticationError`, :class:`RateLimitError`, :class:`LLMRouterError`).

All methods return the raw ``requests.Response`` object after the response has
been validated by ``_handle_response``.
"""

import logging
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from llm_router_lib.exceptions import (
    AuthenticationError,
    RateLimitError,
    LLMRouterError,
)


class HttpRequester:
    """
    Helper for making HTTP calls with built‑in retries and error translation.

    Parameters
    ----------
    base_url : str
        Base URL of the remote service (e.g. ``"https://api.example.com"``).
        A trailing slash is stripped automatically.
    token : str
        Bearer token used for ``Authorization`` header; if empty, no header is added.
    timeout : int, default ``10``
        Per‑request timeout in seconds.
    retries : int, default ``2``
        Number of retry attempts for transient failures (status codes in
        ``status_forcelist``).  The back‑off factor is ``0.5`` seconds.
    logger : Optional[logging.Logger]
        Logger instance; if omitted, a module‑level logger is created.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: int = 10,
        retries: int = 2,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

        if token:
            self.session.headers.update({"Authorization": f"Bearer {token}"})

        self.logger = logger or logging.getLogger(__name__)

        # retry‑policy
        retry_strategy = Retry(
            total=retries,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _full_url(self, path: str) -> str:
        """
        Build the absolute URL for a request.

        Parameters
        ----------
        path : str
            URL path to be appended to ``self.base_url``.  The method ensures
            exactly one ``/`` separates the base and the path.

        Returns
        -------
        str
            Fully qualified URL.
        """
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    @staticmethod
    def _handle_response(resp: requests.Response) -> requests.Response:
        """
        Translate HTTP error codes into library‑specific exceptions.

        The method examines ``resp.status_code`` and raises:

        * :class:`AuthenticationError` for ``401 Unauthorized``.
        * :class:`RateLimitError` for ``429 Too Many Requests``.
        * :class:`LLMRouterError` for any other 4xx/5xx status.

        If the response is successful (2xx), it is returned unchanged.

        Parameters
        ----------
        resp : requests.Response
            The raw response from ``requests``.

        Returns
        -------
        requests.Response
            The same response object if no error is detected.

        Raises
        ------
        AuthenticationError
            When the server returns ``401``.
        RateLimitError
            When the server returns ``429``.
        LLMRouterError
            For any other client or server error (status code 4xx/5xx).
        """
        if resp.status_code == 401:
            raise AuthenticationError("Invalid or missing token")
        if resp.status_code == 429:
            raise RateLimitError("Rate limit exceeded")
        if 400 <= resp.status_code < 600:
            raise LLMRouterError(f"HTTP {resp.status_code}: {resp.text}")
        return resp

    def get(self, path: str, **kwargs) -> requests.Response:
        """
        Perform a ``GET`` request.

        Parameters
        ----------
        path : str
            Relative URL path (e.g. ``"/status"``) that will be combined with the
            base URL.
        **kwargs
            Additional arguments forwarded to ``requests.Session.get`` (e.g.
            ``params`` for query string parameters).

        Returns
        -------
        requests.Response
            The validated response object.
        """
        url = self._full_url(path)
        self.logger.debug("GET %s", url)
        resp = self.session.get(url, timeout=self.timeout, **kwargs)
        return self._handle_response(resp)

    def post(
        self, path: str, json: Optional[Dict[str, Any]] = None, **kwargs
    ) -> requests.Response:
        """
        Perform a ``POST`` request with a JSON body.

        Parameters
        ----------
        path : str
            Relative URL path to post to.
        json : Optional[Dict[str, Any]]
            JSON‑serialisable payload sent as the request body.
        **kwargs
            Additional arguments forwarded to ``requests.Session.post`` (e.g.
            ``files`` or ``headers``).

        Returns
        -------
        requests.Response
            The validated response object.
        """
        url = self._full_url(path)
        self.logger.debug("POST %s | payload=%s", url, json)
        resp = self.session.post(url, json=json, timeout=self.timeout, **kwargs)
        return self._handle_response(resp)
