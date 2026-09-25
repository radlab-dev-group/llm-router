"""
Async HTTP transport for ``llm_router_lib`` (``httpx``‑based).

The :class:`AsyncHttpRequester` is the asynchronous counterpart of
:class:`llm_router_lib.utils.http.HttpRequester` and keeps the same
behaviour contract so that the sync and async clients never drift:

* construction of absolute URLs from a base URL,
* automatic inclusion of a bearer token,
* the same retry policy (status codes from ``RETRY_STATUS_CODELIST``,
  exponential back‑off with ``RETRY_BACKOFF_FACTOR``; connection‑level
  transport failures are retried as well),
* conversion of HTTP error codes into the library‑specific exception
  hierarchy via :func:`llm_router_lib.utils.http.raise_for_status`,
* an additional :meth:`AsyncHttpRequester.stream` context manager for
  streaming (SSE) responses – streaming requests are **not** retried.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, Optional

import httpx

from llm_router_lib.core.constants import (
    RETRY_BACKOFF_FACTOR,
    RETRY_STATUS_CODELIST,
)
from llm_router_lib.exceptions import LLMRouterError
from llm_router_lib.utils.http import raise_for_status


class AsyncHttpRequester:
    """
    Helper for making async HTTP calls with retries and error translation.

    Parameters
    ----------
    base_url : str
        Base URL of the remote service (e.g. ``"https://api.example.com"``).
        A trailing slash is stripped automatically.
    token : str
        Bearer token used for the ``Authorization`` header; if empty, no
        header is added.
    timeout : int, default ``core.constants.DEFAULT_TIMEOUT_SECONDS``
        Per‑request timeout in seconds (used as the default request timeout
        and as the connect timeout for streaming requests).
    retries : int, default ``core.constants.DEFAULT_RETRIES``
        Number of retry attempts for transient failures (status codes in
        ``RETRY_STATUS_CODELIST`` or transport errors).  The back‑off before
        retry ``i`` (1‑based) is ``RETRY_BACKOFF_FACTOR * 2 ** (i - 1)``
        seconds, mirroring the synchronous requester.
    logger : Optional[logging.Logger]
        Logger instance; if omitted, a module‑level logger is created.
    transport : Optional[httpx.AsyncBaseTransport]
        Custom transport (e.g. ``httpx.MockTransport`` in tests); if
        omitted, a default ``httpx.AsyncClient`` is created internally.
    client : Optional[httpx.AsyncClient]
        Pre‑built client (advanced use); takes precedence over
        ``transport``.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        timeout: int = 10,
        retries: int = 2,
        logger: Optional[logging.Logger] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries

        if client is not None:
            self.client = client
        else:
            headers: Dict[str, str] = {}
            if token:
                headers["Authorization"] = f"Bearer {token}"
            self.client = httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(timeout),
                transport=transport,
                follow_redirects=True,
            )

        self.logger = logger or logging.getLogger(__name__)

    def _full_url(self, path: str) -> str:
        """
        Build the absolute URL for a request (same rules as the sync
        :class:`~llm_router_lib.utils.http.HttpRequester`).
        """
        return f"{self.base_url}{path if path.startswith('/') else '/' + path}"

    @staticmethod
    async def _sleep(seconds: float) -> None:
        """
        Back‑off sleep, isolated in a method so tests can patch it.
        """
        await asyncio.sleep(seconds)

    async def _safe_text(self, resp: httpx.Response) -> str:
        """Read the (small) response body for error messages, never raising."""
        try:
            await resp.aread()
            return resp.text
        except Exception:  # pragma: no cover - defensive
            return ""

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Perform an HTTP request with the configured retry policy.

        Retries are applied for status codes in ``RETRY_STATUS_CODELIST`` and
        for transport‑level failures (``httpx.TransportError``).  The final
        response is validated with :func:`raise_for_status` before being
        returned.

        Parameters
        ----------
        method : str
            HTTP method (``"GET"``, ``"POST"``, …).
        path : str
            Relative URL path combined with the base URL.
        json : Optional[Dict[str, Any]]
            Optional JSON‑serialisable request body.
        timeout : Optional[float]
            Per‑request timeout in seconds; defaults to ``self.timeout``.
        **kwargs
            Extra arguments forwarded to ``httpx.AsyncClient.request``.

        Returns
        -------
        httpx.Response
            The validated response object.

        Raises
        ------
        AuthenticationError, RateLimitError, LLMRouterError
            See :func:`llm_router_lib.utils.http.raise_for_status`.
        """
        url = self._full_url(path)
        self.logger.debug("%s %s", method, url)

        attempts = self.retries + 1
        last_transport_exc: Optional[httpx.TransportError] = None

        for attempt in range(attempts):
            if attempt > 0:
                await self._sleep(RETRY_BACKOFF_FACTOR * (2 ** (attempt - 1)))

            try:
                resp = await self.client.request(
                    method,
                    url,
                    json=json,
                    timeout=timeout if timeout is not None else self.timeout,
                    **kwargs,
                )
            except httpx.TransportError as exc:
                last_transport_exc = exc
                continue

            if resp.status_code in RETRY_STATUS_CODELIST and attempt < attempts - 1:
                await resp.aclose()
                continue

            if 400 <= resp.status_code < 600:
                raise_for_status(resp.status_code, await self._safe_text(resp))
            return resp

        raise LLMRouterError(
            f"Request to {url} failed after {attempts} attempt(s): "
            f"{last_transport_exc}"
        ) from last_transport_exc

    async def get(
        self,
        path: str,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform a ``GET`` request (see :meth:`request`)."""
        return await self.request("GET", path, timeout=timeout, **kwargs)

    async def post(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Perform a ``POST`` request with a JSON body (see :meth:`request`)."""
        return await self.request("POST", path, json=json, timeout=timeout, **kwargs)

    @asynccontextmanager
    async def stream(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> AsyncIterator[httpx.Response]:
        """
        Open a streaming response.

        Unlike :meth:`request`, streaming calls are **not** retried: a
        partial body has already been consumed and a blind retry would
        duplicate the generation.  The response is validated for 4xx/5xx
        status codes before being yielded; the body is left open for the
        consumer to iterate (e.g. via ``aiter_lines``) and is closed
        automatically on context exit.

        Parameters
        ----------
        method : str
            HTTP method (``"GET"``, ``"POST"``, …).
        path : str
            Relative URL path combined with the base URL.
        json : Optional[Dict[str, Any]]
            Optional JSON‑serialisable request body.
        timeout : Optional[float]
            Read/write timeout in seconds for the streamed body.  ``None``
            (the default) disables the read timeout – long generations must
            not be cut off by the (short) default request timeout – while the
            connect timeout stays ``self.timeout``.
        **kwargs
            Extra arguments forwarded to ``httpx.AsyncClient.stream``.

        Yields
        ------
        httpx.Response
            The open streaming response.

        Raises
        ------
        AuthenticationError, RateLimitError, LLMRouterError
            See :func:`llm_router_lib.utils.http.raise_for_status`.
        """
        url = self._full_url(path)
        self.logger.debug("%s (stream) %s", method, url)

        effective_timeout = httpx.Timeout(timeout, connect=self.timeout)

        async with self.client.stream(
            method,
            url,
            json=json,
            timeout=effective_timeout,
            **kwargs,
        ) as resp:
            if 400 <= resp.status_code < 600:
                raise_for_status(resp.status_code, await self._safe_text(resp))
            yield resp

    async def aclose(self) -> None:
        """Close the underlying ``httpx.AsyncClient`` to release connections."""
        await self.client.aclose()

    async def __aenter__(self) -> "AsyncHttpRequester":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()
