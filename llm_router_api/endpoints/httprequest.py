"""
Top‑level utilities for executing outbound HTTP calls.

`HttpRequestExecutor` now owns a `StreamHandler` instance, which centralises
all streaming logic.  This keeps the executor lightweight and makes the
stream‑handling code easier to test/mocks.
"""

import requests

from requests import Response
from typing import Any, Dict, Iterator, Optional

from llm_router_api.core.model_handler import ApiModel
from llm_router_api.core.api_types.dispatcher import ApiTypesDispatcher
from llm_router_api.core.stream_handler import StreamHandler, StreamConversion
from llm_router_api.core.errors import sanitize_error_message


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
        """
        Return the internal StreamHandler instance.
        """

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
        api_type = api_model_provider.api_type

        full_url = self._prepare_full_url_ep(
            ep_url=ep_url, api_model_provider=api_model_provider
        )
        if not headers:
            headers = ApiTypesDispatcher.request_headers(
                api_type, api_model_provider
            )

        # resolved system prompt (when any) – the provider type decides how
        # to attach it to the body (OpenAI-style ``messages`` prepend vs.
        # protocol-specific fields).
        system_msg = (
            {"role": "system", "content": prompt_str} if prompt_str else None
        )

        if call_for_each_user_msg:
            return self._call_for_each_user_message(
                ep_url=full_url,
                system_message=system_msg,
                params=params,
                headers=headers,
                api_model_provider=api_model_provider,
            )

        params = ApiTypesDispatcher.request_body(
            api_type, params, api_model_provider, system_msg
        )

        try:
            if self._endpoint.method == "POST":
                return self._call_post_with_payload(
                    ep_url=full_url,
                    params=params,
                    headers=headers,
                    api_model_provider=api_model_provider,
                )
            return self._call_get_with_payload(
                ep_url=full_url,
                params=params,
                headers=headers,
                api_model_provider=api_model_provider,
            )
        except Exception:
            raise  # pylint: disable=raise-missing-from

    # --------------------------------------------------------------------- #
    # Public streaming request – dispatcher to StreamHandler helpers
    # --------------------------------------------------------------------- #
    def stream_response(
        self,
        ep_url: str,
        params: Dict[str, Any],
        api_model_provider: ApiModel,
        options: Optional[Dict[str, Any]] = None,
        stream_type: Optional["StreamConversion"] = None,
        force_text: Optional[str] = None,
    ) -> Iterator[bytes]:
        """
        Streams a response from an endpoint using the specified parameters and streaming type.

        This function enables the dispatching of streaming requests to the appropriate handler
        based on the provided `stream_type` and optional `force_text` override. Different
        streaming conversions are supported, allowing for protocol translation or passthrough
        streaming between various models and APIs. The function also finalizes the request
        body, injects required headers, and prepares the full endpoint URL before processing
        the request.

        Parameters
        ----------
        ep_url : str
            The base endpoint URL to be used for the streaming request.
        params : Dict[str, Any]
            A dictionary containing the request parameters used to build the request body.
        api_model_provider : ApiModel
            Specifies the model provider and its associated api_type, used for generating
            headers and finalizing request data.
        options : Optional[Dict[str, Any]], optional
            Additional options to customize the request, such as timeouts or retry configurations
            (default is None).
        stream_type : Optional["StreamConversion"], optional
            Indicates the type of streaming conversion to apply. Determines whether to perform
            protocol translations and specifies the appropriate handler method for the task
            (default is None).
        force_text : Optional[str], optional
            When specified, forces the output to be treated as text for the requested streaming
            conversion types. Primarily used for guardrail blocking scenarios (default is None).

        Returns
        -------
        Iterator[bytes]
            An iterator that streams the response in byte chunks from the designated handler based
            on the `stream_type` or forced text context.
        """
        self.logger.debug("Stream type: %s", stream_type)

        # ----------------------------------------------------------------- #
        # Pre‑flight force_text override (used by guardrail blocking)
        # ----------------------------------------------------------------- #
        if force_text:
            if stream_type in (
                StreamConversion.OLLAMA,
                StreamConversion.OPENAI_TO_OLLAMA,
            ):
                return self._stream_handler.stream_ollama(
                    url="",
                    payload=params,
                    method="",
                    headers={},
                    options=options,
                    endpoint=self._endpoint,
                    api_model_provider=api_model_provider,
                    force_text=force_text,
                )
            if stream_type in (
                StreamConversion.OPENAI,
                StreamConversion.OLLAMA_TO_OPENAI,
                StreamConversion.ANTHROPIC_TO_OPENAI,
                StreamConversion.VERTEX,
                StreamConversion.VERTEX_TO_OPENAI,
            ):
                return self._stream_handler.stream_openai(
                    url="",
                    payload=params,
                    method="",
                    headers={},
                    options=options,
                    endpoint=self._endpoint,
                    api_model_provider=api_model_provider,
                    force_text=force_text,
                )
            if stream_type in (
                StreamConversion.LMSTUDIO_PASSTHROUGH,
                StreamConversion.OPENAI_TO_LMSTUDIO,
                StreamConversion.OLLAMA_TO_LMSTUDIO,
            ):
                return self._stream_handler.stream_lmstudio(
                    url="",
                    payload=params,
                    method="",
                    headers={},
                    options=options,
                    endpoint=self._endpoint,
                    api_model_provider=api_model_provider,
                    force_text=force_text,
                )

        # common preparation – the provider type finalises the body
        # (model‑name injection for OpenAI‑style backends, full protocol
        # translation otherwise) and builds the authentication headers.
        # The flag is set **before** the body hook: translation providers
        # (e.g. Vertex AI) drop it from the native body, while the default
        # hook keeps it for OpenAI‑style streaming.
        params["stream"] = True
        params = ApiTypesDispatcher.request_body(
            api_model_provider.api_type, params, api_model_provider, None
        )
        full_url = self._prepare_full_url_ep(
            ep_url, api_model_provider=api_model_provider
        )

        method = (self._endpoint.method or "POST").upper()
        headers = ApiTypesDispatcher.request_headers(
            api_model_provider.api_type, api_model_provider
        )

        # ----------------------------------------------------------------- #
        # Dispatch to the appropriate StreamHandler method
        # ----------------------------------------------------------------- #
        match stream_type:
            case StreamConversion.OLLAMA:
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
            case StreamConversion.OPENAI_TO_OLLAMA:
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
            case StreamConversion.OLLAMA_TO_OPENAI:
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
            case StreamConversion.OPENAI_TO_LMSTUDIO:
                return self._stream_handler.stream_openai_to_lmstudio(
                    url=full_url,
                    payload=params,
                    method=method,
                    headers=headers,
                    options=options,
                    endpoint=self._endpoint,
                    api_model_provider=api_model_provider,
                    force_text=force_text,
                )
            case StreamConversion.OLLAMA_TO_LMSTUDIO:
                return self._stream_handler.stream_ollama_to_lmstudio(
                    url=full_url,
                    payload=params,
                    method=method,
                    headers=headers,
                    options=options,
                    endpoint=self._endpoint,
                    api_model_provider=api_model_provider,
                    force_text=force_text,
                )
            case StreamConversion.LMSTUDIO_PASSTHROUGH:
                # LMStudio ↔ LMStudio – the stream format is already OpenAI‑compatible,
                # so we can forward it unchanged.
                return self._stream_handler.stream_lmstudio(
                    url=full_url,
                    payload=params,
                    method=method,
                    headers=headers,
                    options=options,
                    endpoint=self._endpoint,
                    api_model_provider=api_model_provider,
                    force_text=force_text,
                )
            case StreamConversion.ANTHROPIC_TO_OPENAI:
                return self._stream_handler.stream_anthropic_to_openai(
                    url=full_url,
                    payload=params,
                    method=method,
                    headers=headers,
                    options=options,
                    endpoint=self._endpoint,
                    api_model_provider=api_model_provider,
                    force_text=force_text,
                )
            case StreamConversion.OPENAI_TO_ANTHROPIC:
                return self._stream_handler.stream_openai_to_anthropic(
                    url=full_url,
                    payload=params,
                    method=method,
                    headers=headers,
                    options=options,
                    endpoint=self._endpoint,
                    api_model_provider=api_model_provider,
                    force_text=force_text,
                )
            case StreamConversion.ANTHROPIC:
                return self._stream_handler.stream_anthropic(
                    url=full_url,
                    payload=params,
                    method=method,
                    headers=headers,
                    options=options,
                    endpoint=self._endpoint,
                    api_model_provider=api_model_provider,
                    force_text=force_text,
                )
            case StreamConversion.VERTEX:
                return self._stream_handler.stream_vertex(
                    url=full_url,
                    payload=params,
                    method=method,
                    headers=headers,
                    options=options,
                    endpoint=self._endpoint,
                    api_model_provider=api_model_provider,
                    force_text=force_text,
                )
            case StreamConversion.VERTEX_TO_OPENAI:
                return self._stream_handler.stream_vertex_to_openai(
                    url=full_url,
                    payload=params,
                    method=method,
                    headers=headers,
                    options=options,
                    endpoint=self._endpoint,
                    api_model_provider=api_model_provider,
                    force_text=force_text,
                )
            case StreamConversion.OPENAI | None:
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
    def _log_provider_error(
        self,
        method: str,
        ep_url: str,
        api_model_provider: Optional[ApiModel],
        msg: str,
    ) -> None:
        """
        Log the full error details on the server (includes URL, IP, etc.).
        """

        provider_id = api_model_provider.id if api_model_provider else "unknown"
        self.logger.error(
            "[%s] provider %s — URL: %s — error: %s",
            method,
            provider_id,
            ep_url,
            msg,
        )

    @staticmethod
    def _provider_request_error(
        method: str,
        api_model_provider: Optional[ApiModel],
        exc: Exception,
    ) -> RuntimeError:
        """
        Build a sanitized error for the client — uses provider ID, not URL/IP.
        """

        provider_id = api_model_provider.id if api_model_provider else "unknown"
        sanitized = sanitize_error_message(str(exc))
        return RuntimeError(f"[{method}] Provider {provider_id}: {sanitized}")

    @staticmethod
    def _prepare_full_url_ep(ep_url: str, api_model_provider: ApiModel) -> str:
        """
        Build the absolute URL for a given endpoint path.
        """
        return api_model_provider.api_host.rstrip("/") + "/" + ep_url.lstrip("/")

    def _call_for_each_user_message(
        self,
        ep_url: str,
        system_message: Optional[Dict[str, Any]],
        params: Dict[str, Any],
        headers: Optional[Dict[str, Any]] = None,
        api_model_provider: Optional[ApiModel] = None,
    ):
        """
        Send a separate request for each ``user``‑role message.

        The helper builds a list of payloads, each containing the system
        prompt (if any) and a single user message.  Only ``POST`` is
        supported; a ``GET`` will raise an exception.
        """
        if self._endpoint.prepare_response_function is None:
            raise RuntimeError(
                "_prepare_response_function must be implemented "
                "when calling api for each user message"
            )
        if self._endpoint.method != "POST":
            raise RuntimeError(
                "_call_http_request_for_each_user_message "
                'is not implemented for "GET" method'
            )
        if api_model_provider is None:
            raise RuntimeError(
                "_call_for_each_user_message requires an api_model_provider"
            )

        _payloads = []
        for m in params.get("messages", []):
            if m.get("role", "?") == "user":
                _params = params.copy()
                _params["messages"] = (
                    [system_message] if system_message else []
                ) + [m]
                # per‑payload body finalisation (model injection /
                # protocol translation) – one call per user message.
                _params = ApiTypesDispatcher.request_body(
                    api_model_provider.api_type,
                    _params,
                    api_model_provider,
                    None,
                )
                _payloads.append([_params, m["content"]])

        contents = []
        responses = []
        for payload, content in _payloads:
            response = self._call_post_with_payload(
                ep_url=ep_url,
                params=payload,
                return_raw_response=True,
                headers=headers,
                api_model_provider=api_model_provider,
            )
            response.raise_for_status()
            contents.append(content)
            responses.append(response)

        return self._endpoint.prepare_response_function(responses, contents)

    def _call_post_with_payload(
        self,
        ep_url: str,
        params: Dict[str, Any],
        return_raw_response: bool = False,
        headers: Optional[Dict[str, Any]] = None,
        api_model_provider: Optional[ApiModel] = None,
    ) -> Optional[Dict[str, Any] | Response]:
        """
        Issue a ``POST`` request with a JSON payload.
        """
        try:
            response = requests.post(
                ep_url,
                json=params,
                timeout=self._endpoint.timeout,
                headers=headers,
            )
        except requests.RequestException as exc:
            self._log_provider_error("POST", ep_url, api_model_provider, str(exc))

            raise self._provider_request_error(
                "POST", api_model_provider, exc
            ) from exc

        status_code = getattr(response, "status_code", None)
        if api_model_provider is not None and status_code is not None:
            # Let the provider type react to the status (e.g. evicting Google
            # credentials the upstream rejected) before anyone consumes it.
            ApiTypesDispatcher.on_response_status(
                api_model_provider.api_type,
                api_model_provider,
                int(status_code),
            )

        if return_raw_response:
            return response
        return self._endpoint.return_http_response(
            response=response, api_model_provider=api_model_provider
        )

    def _call_get_with_payload(
        self,
        ep_url: str,
        params: Dict[str, Any],
        headers: Optional[Dict[str, Any]] = None,
        api_model_provider: Optional[ApiModel] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Issue a ``GET`` request with query parameters.
        """
        try:
            response = requests.get(
                ep_url,
                params=params,
                timeout=self._endpoint.timeout,
                headers=headers,
            )
        except requests.RequestException as exc:
            self._log_provider_error("GET", ep_url, api_model_provider, str(exc))

            raise self._provider_request_error(
                "GET", api_model_provider, exc
            ) from exc

        status_code = getattr(response, "status_code", None)
        if api_model_provider is not None and status_code is not None:
            ApiTypesDispatcher.on_response_status(
                api_model_provider.api_type,
                api_model_provider,
                int(status_code),
            )

        return self._endpoint.return_http_response(
            response=response, api_model_provider=api_model_provider
        )
