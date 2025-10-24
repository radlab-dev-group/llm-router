"""
Top‑level utilities for executing outbound HTTP calls.

The module defines :class:`HttpRequestExecutor`, a helper that centralises
all HTTP interactions performed by ``EndpointWithHttpRequestI`` instances.
It supports regular (blocking) requests as well as streaming responses,
including special handling for Ollama‑compatible NDJSON streams.

Typical usage:

    executor = HttpRequestExecutor(endpoint)
    response = executor.call_http_request(
        ep_url="/v1/chat/completions",
        params={...},
        prompt_str="You are a helpful assistant.",
    )

The executor pulls configuration such as timeout, authentication token,
default headers and the model identifier from the owning endpoint, so
callers only need to supply endpoint‑specific parameters.
"""

import json

import requests
import datetime

from requests import Response
from typing import Optional, Dict, Any, Iterator

from llm_router_api.base.model_handler import ApiModel


class HttpRequestExecutor:
    """
    Centralised helper for performing outbound HTTP calls.

    It aggregates the logic that was previously duplicated across several
    private helpers (``_call_http_request``, ``_call_http_request_stream``,
    ``_call_http_request_stream_ollama``).  The executor obtains the
    timeout, logger, authentication token and model information from the
    owning ``EndpointWithHttpRequestI`` instance and exposes a small public
    API:

    * :meth:`call_http_request` – synchronous request returning a parsed
      JSON payload or the raw :class:`requests.Response`.
    * :meth:`stream_response` – generator yielding byte chunks from a
      streaming endpoint, optionally converting the stream to Ollama‑compatible
      NDJSON.
    * Several ``_``‑prefixed private helpers that perform the actual
      ``GET``/``POST`` calls and stream processing.

    The class is deliberately lightweight – it does not hold any network
    resources itself and can be instantiated per‑request if desired.
    """

    def __init__(self, endpoint: "EndpointWithHttpRequestI"):
        """
        Initialise the executor with a reference to its endpoint.

        Parameters
        ----------
        endpoint:
            The ``EndpointWithHttpRequestI`` instance whose configuration
            (timeout, logger, model handler, etc.) will be used for all
            HTTP interactions performed by this executor.
        """
        self._endpoint = endpoint
        self.logger = endpoint.logger

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

        The model identifier is injected into *params* and the full URL is
        constructed from the endpoint's host and the supplied ``ep_url``.
        If ``call_for_each_user_msg`` is ``True`` a separate request is
        sent for each user‑role message in ``params["messages"]``.  The
        method returns either a parsed JSON dictionary or the raw
        :class:`requests.Response` object, depending on the endpoint's
        configuration.

        Parameters
        ----------
        ep_url:
            Relative path (e.g. ``"/v1/chat/completions"``) appended to the
            model host.
        params:
            Dictionary of request parameters; will be mutated to include the
            model name and, optionally, the system prompt.
        api_model_provider:
            Model provider used to construct API requests.
        prompt_str:
            Optional system‑prompt text to prepend to the conversation.
        call_for_each_user_msg:
            When ``True`` the request is split per user message.
        headers:
            Optional additional HTTP headers; ``Authorization`` is added
            automatically when an API token is configured.

        Returns
        -------
        dict | Response | None
            Parsed JSON payload, the raw ``Response`` object, or ``None`` if
            the endpoint decides not to return a value.

        Raises
        ------
        RuntimeError
            Propagated from underlying ``requests`` exceptions.
        """
        # inject model name
        params["model"] = (
            api_model_provider.model_path
            if api_model_provider.model_path
            else api_model_provider.name
        )

        full_url = self._prepare_full_url_ep(
            ep_url, api_model_provider=api_model_provider
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

        # self.logger.debug(json.dumps(params or {}, indent=2, ensure_ascii=False))

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

    def stream_response(
        self,
        ep_url: str,
        params: Dict[str, Any],
        api_model_provider: ApiModel,
        is_ollama: bool = False,
        is_generic_to_ollama: bool = False,
    ) -> Iterator[bytes]:
        """
        Perform a streaming request and yield byte chunks.

        ``params`` is enriched with ``model`` and ``stream=True`` before the
        request is issued.  If ``is_ollama`` is ``True`` the raw stream is
        transformed into Ollama‑compatible NDJSON; otherwise the raw bytes
        from the remote service are yielded unchanged.

        Parameters
        ----------
        ep_url:
            Relative endpoint path to which the request is sent.
        params:
            Payload parameters; ``model`` and ``stream`` are added automatically.
        api_model_provider:
            Model provider used to construct API requests.
        is_ollama:
            Flag indicating whether Ollama‑specific conversion should be
            applied to the incoming stream.
        is_generic_to_ollama:
            Flag to stream a response from an Ollama endpoint
            and convert it to the OpenAI‑compatible format

        Returns
        -------
        Iterator[bytes]
            An iterator yielding chunks of the HTTP response body.

        Raises
        ------
        RuntimeError
            When is_ollama and is_generic_to_ollama are ``True``.
        """

        if is_ollama and is_generic_to_ollama:
            raise RuntimeError(
                "is_ollama and is_generic_to_ollama are mutually exclusive!"
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
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        token = api_model_provider.api_token
        if token:
            headers["Authorization"] = f"Bearer {token}"

        params = self._convert_ollama_messages_if_needed(params=params)
        if is_ollama:
            return self._stream_ollama(
                full_url,
                params,
                method,
                headers,
                api_model_provider=api_model_provider,
            )
        if is_generic_to_ollama:
            return self._stream_generic_to_ollama(
                full_url,
                params,
                method,
                headers,
                api_model_provider=api_model_provider,
            )
        else:
            return self._stream_generic(
                full_url,
                params,
                method,
                headers,
                api_model_provider=api_model_provider,
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
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
        _payloads = []
        for m in params.get("messages", []):
            if m.get("role", "?") == "user":
                _params = params.copy()
                _params["messages"] = [system_message, m]
                _payloads.append([_params, m["content"]])

        if self._endpoint.method != "POST":
            raise Exception(
                "_call_http_request_for_each_user_message "
                'is not implemented for "GET" method'
            )

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

        if self._endpoint._prepare_response_function is None:
            raise Exception(
                "_prepare_response_function must be implemented "
                "when calling api for each user message"
            )
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

    def _stream_generic(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        api_model_provider: ApiModel,
    ) -> Iterator[bytes]:
        """
        Perform a generic streaming request without Ollama conversion.

        The function yields each line of the response as a UTF‑8‑encoded
        ``bytes`` object, preserving the original line endings.

        Parameters
        ----------
        url:
            Full request URL.
        payload:
            JSON payload for ``POST`` or query parameters for ``GET``.
        method:
            HTTP method – ``POST`` or ``GET`` (case‑insensitive).
        headers:
            Dictionary of request headers.

        Returns
        -------
        Iterator[bytes]
            An iterator over the streamed response lines.
        """

        def _iter() -> Iterator[bytes]:
            try:
                if method == "POST":
                    with requests.post(
                        url,
                        json=payload,
                        timeout=self._endpoint.timeout,
                        stream=True,
                        headers=headers,
                    ) as r:
                        r.raise_for_status()
                        for line in r.iter_lines(decode_unicode=False):
                            if line:
                                yield line + b"\n"
                else:
                    with requests.get(
                        url,
                        params=payload,
                        timeout=self._endpoint.timeout,
                        stream=True,
                        headers=headers,
                    ) as r:
                        r.raise_for_status()
                        for line in r.iter_lines(decode_unicode=False):
                            if line:
                                yield line + b"\n"
            except requests.RequestException as exc:
                err = {"error": str(exc)}
                yield (json.dumps(err, ensure_ascii=False) + "\n").encode("utf-8")
            finally:
                self._endpoint.unset_model(
                    params=payload, api_model_provider=api_model_provider
                )

        return _iter()

    def _stream_ollama(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        api_model_provider: ApiModel,
    ) -> Iterator[bytes]:
        """
        Perform a streaming request and convert the stream to Ollama NDJSON.

        The helper first normalises the ``messages`` payload (if required) and
        then streams the response, feeding each chunk to
        :meth:`_parse_ollama_stream` which yields Ollama‑compatible
        byte chunks.

        Parameters
        ----------
        url:
            Destination URL.
        payload:
            Request payload; may be altered by ``_convert_ollama_messages_if_needed``.
        method:
            ``POST`` or ``GET``.
        headers:
            HTTP headers, including authentication when configured.

        Returns
        -------
        Iterator[bytes]
            An iterator yielding Ollama‑compatible NDJSON lines.
        """

        def _iter() -> Iterator[bytes]:
            try:
                if method == "POST":
                    with requests.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=self._endpoint.timeout,
                        stream=True,
                    ) as resp:
                        resp.raise_for_status()
                        for chunk in self._parse_ollama_stream(
                            resp, api_model_provider=api_model_provider
                        ):
                            yield chunk
                else:
                    with requests.get(
                        url,
                        params=payload,
                        headers=headers,
                        timeout=self._endpoint.timeout,
                        stream=True,
                    ) as resp:
                        resp.raise_for_status()
                        for chunk in self._parse_ollama_stream(
                            resp, api_model_provider=api_model_provider
                        ):
                            yield chunk
            except requests.RequestException as exc:
                yield (json.dumps({"error": str(exc)}) + "\n").encode("utf-8")
            finally:
                self._endpoint.unset_model(
                    params=payload, api_model_provider=api_model_provider
                )

        return _iter()

    # ------------------------------------------------------------------
    # Ollama‑specific helpers
    # ------------------------------------------------------------------
    def _ollama_chunk(
        self,
        delta: str,
        done: bool = False,
        usage: Dict[str, int] = None,
        api_model_provider: ApiModel = None,
    ) -> bytes:
        """
        Build a single Ollama‑compatible NDJSON line.

        Parameters
        ----------
        delta:
            Text fragment to include in the ``message.content`` field.
        done:
            When ``True`` the chunk signals the end of the stream and may
            contain usage statistics.
        usage:
            Optional mapping with ``prompt_tokens`` and ``completion_tokens``.

        Returns
        -------
        bytes
            JSON line encoded as UTF‑8, terminated by a newline.
        """
        obj = {
            "model": api_model_provider.name,
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            "done": done,
        }

        if not done:
            obj["message"] = {"role": "assistant", "content": delta}
        else:
            obj["message"] = {"role": "assistant", "content": ""}
            if usage:
                obj["prompt_eval_count"] = usage.get("prompt_tokens", 0)
                obj["eval_count"] = usage.get("completion_tokens", 0)
            else:
                obj["prompt_eval_count"] = 0
                obj["eval_count"] = 0
            obj["total_duration"] = 0
            obj["load_duration"] = 0
            obj["prompt_eval_duration"] = 0
            obj["eval_duration"] = 0

        return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")

    def _parse_ollama_stream(
        self, response: Response, api_model_provider: ApiModel
    ) -> Iterator[bytes]:
        """
        Parse an OpenAI‑style SSE/NDJSON stream and emit Ollama NDJSON.

        The function walks through each line of the incoming stream,
        handling both ``data:``‑prefixed SSE events and plain NDJSON.
        It extracts the assistant delta text, forwards usage statistics,
        and emits a final ``done`` chunk when the remote stream ends.

        Parameters
        ----------
        response:
            The ``requests.Response`` object with ``stream=True``.

        Returns
        -------
        Iterator[bytes]
            Byte chunks representing Ollama‑compatible NDJSON lines.
        """
        sent_done = False
        usage_data = None
        for raw in response.iter_lines(decode_unicode=False):
            if not raw:
                continue
            try:
                line = raw.decode("utf-8").strip()
            except UnicodeDecodeError:
                # If UTF-8 fails, skip this line
                continue

            # OpenAI SSE style
            if line.startswith("data:"):
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    if not sent_done:
                        yield self._ollama_chunk(
                            delta="",
                            done=True,
                            usage=usage_data,
                            api_model_provider=api_model_provider,
                        )
                        sent_done = True
                    continue
                try:
                    event = json.loads(data_str)
                except Exception:
                    yield (line + "\n").encode("utf-8")
                    continue

                if "usage" in event:
                    usage_data = event["usage"]

                # extract delta text
                delta_text = ""
                try:
                    choices = event.get("choices", [])
                    if choices:
                        delta_obj = (
                            choices[0].get("delta") or choices[0].get("text") or {}
                        )
                        if isinstance(delta_obj, dict):
                            delta_text = delta_obj.get("content") or ""
                        elif isinstance(delta_obj, str):
                            delta_text = delta_obj
                except Exception:
                    delta_text = ""

                if delta_text:
                    yield self._ollama_chunk(
                        delta=delta_text,
                        done=False,
                        api_model_provider=api_model_provider,
                    )

                # finish reason → final chunk
                try:
                    choices = event.get("choices", [])
                    if choices and choices[0].get("finish_reason") and not sent_done:
                        yield self._ollama_chunk(
                            delta="",
                            done=True,
                            usage=usage_data,
                            api_model_provider=api_model_provider,
                        )
                        sent_done = True
                except Exception:
                    pass
                continue

            # NDJSON without "data:" prefix
            try:
                evt = json.loads(line)

                if "usage" in evt:
                    usage_data = evt["usage"]

                delta_text = ""
                if "choices" in evt:
                    ch = evt["choices"]
                    if ch:
                        d = ch[0].get("delta") or ch[0].get("text") or {}
                        if isinstance(d, dict):
                            delta_text = d.get("content") or ""
                        elif isinstance(d, str):
                            delta_text = d
                    if delta_text:
                        yield self._ollama_chunk(
                            delta_text,
                            done=False,
                            api_model_provider=api_model_provider,
                        )
                    if ch and ch[0].get("finish_reason") and not sent_done:
                        yield self._ollama_chunk(
                            delta="",
                            done=True,
                            usage=usage_data,
                            api_model_provider=api_model_provider,
                        )
                        sent_done = True
                elif evt.get("done") is True and not sent_done:
                    yield self._ollama_chunk(
                        delta="",
                        done=True,
                        usage=usage_data,
                        api_model_provider=api_model_provider,
                    )
                    sent_done = True
                else:
                    yield (line + "\n").encode("utf-8")
            except Exception:
                yield (line + "\n").encode("utf-8")
        if not sent_done:
            yield self._ollama_chunk(
                delta="",
                done=True,
                usage=usage_data,
                api_model_provider=api_model_provider,
            )

    def _stream_generic_to_ollama(
        self,
        url: str,
        payload: Dict[str, Any],
        method: str,
        headers: Dict[str, Any],
        api_model_provider: ApiModel,
    ) -> Iterator[bytes]:
        """
        Stream a response from an Ollama endpoint and convert it to the
        OpenAI‑compatible format used by vLLM (i.e. the same JSON‑lines that
        ``vllm``/``openai`` return for streaming completions).

        The incoming stream is expected to be Ollama NDJSON (the format
        produced by :meth:`_stream_ollama`).  Each line is parsed and
        transformed into a JSON ``chat.completion.chunk`` object.  The
        generator yields UTF‑8‑encoded bytes terminated by a newline.

        Parameters
        ----------
        url:
            Full request URL.
        payload:
            JSON payload for ``POST`` or query parameters for ``GET``.
        method:
            HTTP method – ``POST`` or ``GET`` (case‑insensitive).
        headers:
            Request headers, including authentication when configured.

        Returns
        -------
        Iterator[bytes]
            Byte chunks representing OpenAI‑style streaming responses.
        """

        def _iter() -> Iterator[bytes]:
            try:
                # Perform the actual HTTP request (same logic as _stream_generic)
                if method == "POST":
                    request_ctx = requests.post(
                        url,
                        json=payload,
                        timeout=self._endpoint.timeout,
                        stream=True,
                        headers=headers,
                    )
                else:
                    request_ctx = requests.get(
                        url,
                        params=payload,
                        timeout=self._endpoint.timeout,
                        stream=True,
                        headers=headers,
                    )
                with request_ctx as resp:
                    resp.raise_for_status()
                    for raw_line in resp.iter_lines(decode_unicode=False):
                        if not raw_line:
                            continue
                        try:
                            ollama_obj = json.loads(
                                raw_line.decode("utf-8", errors="replace")
                            )
                        except Exception:
                            # If parsing fails, forward the raw line unchanged
                            yield (raw_line + b"\n")
                            continue

                        # Build a base chunk dictionary
                        base_chunk = {
                            "id": "chatcmpl-"
                            + datetime.datetime.utcnow().strftime("%Y%m%d%H%M%S"),
                            "object": "chat.completion.chunk",
                            "created": int(datetime.datetime.utcnow().timestamp()),
                            "model": ollama_obj.get(
                                "model", self._endpoint.api_model.name
                            ),
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {},
                                    "finish_reason": None,
                                }
                            ],
                        }

                        # If the Ollama payload signals the end of the stream
                        if ollama_obj.get("done"):
                            base_chunk["choices"][0]["finish_reason"] = "stop"
                            # No delta content for the final chunk
                            yield (
                                json.dumps(base_chunk, ensure_ascii=False) + "\n"
                            ).encode("utf-8")
                            continue

                        # Normal content chunk – extract the assistant delta
                        delta_text = ollama_obj.get("message", {}).get("content", "")
                        if delta_text:
                            base_chunk["choices"][0]["delta"] = {
                                "content": delta_text
                            }
                            yield (
                                json.dumps(base_chunk, ensure_ascii=False) + "\n"
                            ).encode("utf-8")
            except requests.RequestException as exc:
                err = {"error": str(exc)}
                yield (json.dumps(err) + "\n").encode("utf-8")
            finally:
                self._endpoint.unset_model(
                    params=payload, api_model_provider=api_model_provider
                )

        return _iter()

    @staticmethod
    def _convert_ollama_messages_if_needed(params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalise a ``messages`` payload for Ollama compatibility.

        Ollama expects an alternating ``user``/``assistant`` sequence.
        This helper inserts empty ``assistant`` messages where necessary
        so that a consecutive series of user messages is transformed
        into a valid dialogue.

        Parameters
        ----------
        params:
            Request payload possibly containing a ``messages`` list.

        Returns
        -------
        dict
            The possibly‑modified payload with a correctly ordered
            ``messages`` list.
        """
        if not "messages" in params:
            return params

        messages = params["messages"]
        if len(messages) == 1:
            return params

        if messages[0].get("role") == "user" and messages[1].get("role") == "user":
            skip_last = False
            _messages = []
            _msg_count = len(messages)
            for _num, message in enumerate(messages):
                skip_last = False
                _messages.append(message)
                if message["role"] == "assistant":
                    continue

                if _num + 1 < _msg_count:
                    if messages[_num + 1]["role"] == "assistant":
                        continue
                _messages.append({"role": "assistant", "content": ""})
                skip_last = True

            if skip_last:
                _messages.pop(-1)

            params["messages"] = _messages

        return params
