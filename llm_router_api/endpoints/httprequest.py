"""
Top‑level utilities for executing outbound HTTP calls.

`HttpRequestExecutor` now owns a `StreamHandler` instance, which centralises
all streaming logic.  This keeps the executor lightweight and makes the
stream‑handling code easier to test/mocks.
"""

import requests
from requests import Response
from typing import Optional, Dict, Any, Iterator

from llm_router_api.core.model_handler import ApiModel
from llm_router_api.core.stream_handler import StreamHandler


class HttpRequestExecutor:
    """
    Centralised helper for performing outbound HTTP calls.

    The executor aggregates the logic that was previously duplicated across
    several private helpers.  It now also contains a `StreamHandler`
    instance used for all streaming interactions.
    """

    def __init__(self, endpoint):
        """
        Initialise the executor with a reference to its endpoint.
        """
        self._endpoint = endpoint
        self.logger = endpoint.logger

        self._stream_handler = StreamHandler()

    @property
    def stream_handler(self):
        return self._stream_handler

    # --------------------------------------------------------------------- #
    # Public synchronous request
    # --------------------------------------------------------------------- #
    def call_http_request(
        self,
        ep_url: str,
        params: Dict[str, Any],
        api_model_provider: ApiModel,
        prompt_str: Optional[str] = None,
        call_for_each_user_msg: bool = False,
        headers: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any] | Response]:
        """
        Execute a regular (non‑streaming) HTTP request.
        """
        # inject model name
        params["model"] = (
            api_model_provider.model_path
            if api_model_provider.model_path
            else api_model_provider.name
        )

        full_url = self._prepare_full_url_ep(
            ep_url=ep_url, api_model_provider=api_model_provider
        )
        if not headers:
            headers = {"Content-Type": "application/json"}

        # auth header
        token_str = api_model_provider.api_token
        if token_str:
            headers["Authorization"] = f"Bearer {token_str}"

        # prepend system prompt if required
        system_msg = {}
        if prompt_str:
            system_msg = {"role": "system", "content": prompt_str}

        if call_for_each_user_msg:
            return self._call_for_each_user_message(
                ep_url=full_url,
                system_message=system_msg,
                params=params,
                headers=headers,
            )

        if prompt_str:
            params["messages"] = [system_msg] + params.get("messages", [])

        try:
            if self._endpoint.method == "POST":
                return self._call_post_with_payload(
                    ep_url=full_url,
                    params=params,
                    headers=headers,
                )
            return self._call_get_with_payload(
                ep_url=full_url,
                params=params,
                headers=headers,
            )
        except Exception:
            raise

    # --------------------------------------------------------------------- #
    # Public streaming request – dispatcher to StreamHandler helpers
    # --------------------------------------------------------------------- #
    def stream_response(
        self,
        ep_url: str,
        params: Dict[str, Any],
        api_model_provider: ApiModel,
        options: Optional[Dict[str, Any]] = None,
        is_ollama: bool = False,
        is_openai_to_ollama: bool = False,
        is_ollama_to_openai: bool = False,
        is_openai: bool = False,
        is_openai_to_lmstudio: bool = False,
        is_ollama_to_lmstudio: bool = False,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Perform a streaming request and yield byte chunks.

        Conventions:
        - "openai" means OpenAI-style SSE streaming (also used by LM Studio).
        - "ollama" means Ollama NDJSON streaming.
        - *_to_* flags indicate stream conversion direction.
        """

        self.logger.debug(
            "Stream type:\n"
            f"  * is_ollama={is_ollama}\n"
            f"  * is_openai={is_openai}\n"
            f"  * is_openai_to_ollama={is_openai_to_ollama}\n"
            f"  * is_openai_to_lmstudio={is_openai_to_lmstudio}\n"
            f"  * is_ollama_to_openai={is_ollama_to_openai}\n"
            f"  * is_ollama_to_lmstudio={is_ollama_to_lmstudio}\n"
        )

        selected = [is_ollama, is_openai_to_ollama, is_ollama_to_openai, is_openai]
        if sum(1 for x in selected if x) != 1:
            raise RuntimeError(
                "Exactly one streaming mode must be selected: "
                "is_ollama | is_openai | is_openai_to_ollama | is_ollama_to_openai "
            )

        # common preparation
        params["model"] = (
            api_model_provider.model_path
            if api_model_provider.model_path
            else api_model_provider.name
        )
        params["stream"] = True
        full_url = self._prepare_full_url_ep(
            ep_url, api_model_provider=api_model_provider
        )

        method = (self._endpoint.method or "POST").upper()
        headers = {"Content-Type": "application/json"}
        token = api_model_provider.api_token
        if token:
            headers["Authorization"] = f"Bearer {token}"

        if is_ollama:
            return self._stream_handler.stream_ollama(
                url=full_url,
                payload=params,
                method=method,
                headers=headers,
                options=options,
                endpoint=self._endpoint,
                api_model_provider=api_model_provider,
                force_text=force_text,
            )

        if is_openai_to_ollama:
            return self._stream_handler.stream_openai_to_ollama(
                url=full_url,
                payload=params,
                method=method,
                headers=headers,
                options=options,
                endpoint=self._endpoint,
                api_model_provider=api_model_provider,
                force_text=force_text,
            )

        if is_ollama_to_openai:
            return self._stream_handler.stream_ollama_to_openai(
                url=full_url,
                payload=params,
                method=method,
                headers=headers,
                options=options,
                endpoint=self._endpoint,
                api_model_provider=api_model_provider,
                force_text=force_text,
            )

        if is_openai_to_lmstudio:
            pass

        if is_ollama_to_lmstudio:
            pass

        # is_openai
        return self._stream_handler.stream_openai(
            url=full_url,
            payload=params,
            method=method,
            headers=headers,
            options=options,
            endpoint=self._endpoint,
            api_model_provider=api_model_provider,
            force_text=force_text,
        )

    # --------------------------------------------------------------------- #
    # Private helpers
    # --------------------------------------------------------------------- #
    @staticmethod
    def _prepare_full_url_ep(ep_url: str, api_model_provider: ApiModel) -> str:
        full_url = api_model_provider.api_host.rstrip("/") + "/" + ep_url.lstrip("/")
        return full_url

    def _call_for_each_user_message(
        self,
        ep_url: str,
        system_message: Dict[str, Any],
        params: Dict[str, Any],
        headers: Optional[Dict[str, Any]] = None,
    ):
        """
        Send a separate request for each user‑role message.

        The helper builds a list of payloads, each containing the system
        prompt (if any) and a single user message.  Only ``POST`` is
        supported; a ``GET`` will raise an exception.

        Parameters
        ----------
        ep_url:
            Fully‑qualified request URL.
        system_message:
            Optional system‑prompt dictionary injected into each payload.
        params:
            Original request parameters containing the ``messages`` list.
        headers:
            Optional HTTP headers to include with each request.

        Returns
        -------
        Any
            The value returned by the endpoint's
            ``_prepare_response_function`` – typically a list of processed
            responses.

        Raises
        ------
        Exception
            If the endpoint method is not ``POST`` or if the required
            ``_prepare_response_function`` is missing.
        """
        if self._endpoint._prepare_response_function is None:
            raise Exception(
                "_prepare_response_function must be implemented "
                "when calling api for each user message"
            )

        if self._endpoint.method != "POST":
            raise Exception(
                "_call_http_request_for_each_user_message "
                'is not implemented for "GET" method'
            )

        _payloads = []
        for m in params.get("messages", []):
            if m.get("role", "?") == "user":
                _params = params.copy()
                _params["messages"] = [system_message, m]
                _payloads.append([_params, m["content"]])

        contents = []
        responses = []
        for payload, content in _payloads:
            # self.logger.debug(f"Request payload: {payload}")

            response = self._call_post_with_payload(
                ep_url=ep_url,
                params=payload,
                return_raw_response=True,
                headers=headers,
            )
            response.raise_for_status()
            contents.append(content)
            responses.append(response)

            # self.logger.debug(response.json())
        return self._endpoint._prepare_response_function(responses, contents)

    def _call_post_with_payload(
        self,
        ep_url: str,
        params: Dict[str, Any],
        return_raw_response: bool = False,
        headers: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any] | Response]:
        """
        Issue a ``POST`` request with a JSON payload.

        Parameters
        ----------
        ep_url:
            Destination URL.
        params:
            JSON‑serialisable payload to be sent in the request body.
        return_raw_response:
            When ``True`` the raw :class:`requests.Response` is returned
            without invoking ``EndpointWithHttpRequestI.return_http_response``.
        headers:
            Optional HTTP headers; ``Content‑Type`` and ``Authorization``
            are added automatically when appropriate.

        Returns
        -------
        dict | Response | None
            Parsed response (via ``return_http_response``) or the raw
            ``Response`` when ``return_raw_response`` is ``True``.

        Raises
        ------
        RuntimeError
            If the underlying ``requests.post`` call fails.
        """
        try:
            response = requests.post(
                ep_url,
                json=params,
                timeout=self._endpoint.timeout,
                headers=headers,
            )
        except requests.RequestException as exc:
            self.logger.exception(exc)
            raise RuntimeError(f"POST request to {ep_url} failed: {exc}") from exc

        if return_raw_response:
            return response
        return self._endpoint.return_http_response(response=response)

    def _call_get_with_payload(
        self,
        ep_url: str,
        params: Dict[str, Any],
        headers: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Issue a ``GET`` request with query parameters.

        Parameters
        ----------
        ep_url:
            Destination URL.
        params:
            Mapping of query string parameters.
        headers:
            Optional HTTP headers; authentication is added automatically.

        Returns
        -------
        dict | None
            Parsed JSON response as processed by the endpoint.

        Raises
        ------
        RuntimeError
            If the underlying ``requests.get`` call raises an exception.
        """
        try:
            response = requests.get(
                ep_url,
                params=params,
                timeout=self._endpoint.timeout,
                headers=headers,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"GET request to {ep_url} failed: {exc}") from exc
        return self._endpoint.return_http_response(response=response)
