"""
HTTP dispatch and retry orchestration for HTTP‑request‑enabled endpoints.

This module hosts the request‑issuing part of
:class:`llm_router_api.endpoints.endpoint_i.EndpointWithHttpRequestI`:

* sending the prepared payload to the external service,
* recording Prometheus provider metrics (latency, errors, retries, tokens),
* retrying transient provider failures (status codes such as ``429``/``5xx``).

The logic was moved here **verbatim** from the endpoint class (see the
``http_dispatch`` refactor); the class keeps a thin delegate so existing
call sites and tests are unaffected.

Dependencies on the owning endpoint are resolved *dynamically* (at call
time), exactly like the original in‑class method did, so late‑bound
overrides, monkey‑patches and subclassing keep working unchanged.
"""

import json
import time
import random
import logging

from typing import Any, Dict, Iterator, List, Optional, Tuple, Type

from llm_router_api.core.errors import (
    ProviderStreamError,
    sanitize_error_message,
)
from llm_router_api.core.provider_attempts import with_attempted_provider
from llm_router_api.core.stream_handler import StreamConversion

# ---------------------------------------------------------------------------
# Retry policy (moved verbatim from ``EndpointWithHttpRequestI.RetryResponse``)
# ---------------------------------------------------------------------------
# Code - definition
#  * 429 - Too Many Requests (rate limited)
#  * 500 - Internal Server Error
#  * 502 - Bad Gateway
#  * 503 - Service Unavailable
#  * 504 - Gateway Timeout
# By default **every** 4xx/5xx answer retriggers the request: an error status
# usually describes the provider that produced it (model still loading, context
# too long for that host, expired token...), so the next attempt is routed to a
# different provider - and only then to the model's ``fallback_model``.
RETRY_WHEN_STATUS: List[int] = [429, 500, 502, 503, 504]
RETRY_ON_ANY_ERROR_STATUS: bool = True
TIME_TO_WAIT_SEC: float = 0.1  # base backoff delay in seconds
MAX_RECONNECTIONS: int = 10  # upper bound on retry attempts
MAX_BACKOFF_SEC: float = 2.0  # cap for the exponential backoff delay


class RetryPolicy:
    """
    Configuration for automatic retry handling when an outbound HTTP
    request fails with a transient error.

    Attributes
    ----------
    RETRY_WHEN_STATUS : List[int]
        HTTP status codes that trigger a retry.  Includes client and
        server error codes that are typically recoverable (429, 500,
        502, 503, 504).  Used as the whole allow-list only when
        ``RETRY_ON_ANY_ERROR_STATUS`` is disabled.
    RETRY_ON_ANY_ERROR_STATUS : bool
        When ``True`` (default) any 4xx/5xx status retriggers the request
        on another provider of the same model (or on the ``fallback_model``
        once the model's own providers were exhausted).
    TIME_TO_WAIT_SEC : float
        Base backoff delay in seconds.  The actual delay for attempt *n*
        is ``min(TIME_TO_WAIT_SEC * 2**n, MAX_BACKOFF_SEC)`` plus a small
        random jitter.
    MAX_RECONNECTIONS : int
        Upper bound on how many retry attempts will be made before giving
        up.
    MAX_BACKOFF_SEC : float
        Cap applied to the exponential backoff delay.

    Replayability
    -------------
    Retrying is only safe when the request body can be reproduced.  All
    endpoints in this codebase build the outbound body from a plain JSON
    *params* dictionary (see ``HttpRequestExecutor.call_http_request``),
    so the body is always replayable and may be sent to another provider.
    Bodies that cannot be reproduced (e.g. one-shot streams) must **not**
    be retried — such requests must bypass this dispatch path.
    """

    RETRY_WHEN_STATUS = RETRY_WHEN_STATUS
    RETRY_ON_ANY_ERROR_STATUS = RETRY_ON_ANY_ERROR_STATUS
    TIME_TO_WAIT_SEC = TIME_TO_WAIT_SEC
    MAX_RECONNECTIONS = MAX_RECONNECTIONS
    MAX_BACKOFF_SEC = MAX_BACKOFF_SEC


class HttpDispatch:
    """
    Execute the outbound HTTP call for an endpoint and handle retries.

    The dispatch is owned by the endpoint (passed in the constructor) and
    resolves all collaborators — HTTP executor, logger, metrics accessor,
    model release, error‑response builder and the recursive ``run_ep``
    entry point — *at call time*, mirroring the original in‑class
    behaviour of :meth:`EndpointWithHttpRequestI._return_response_or_rerun`.
    """

    def __init__(self, endpoint: Any, retry_policy: Optional[Type] = None) -> None:
        """
        Bind the owning endpoint.

        Parameters
        ----------
        endpoint:
            The endpoint instance this dispatcher works for.  It must expose
            ``_http_executor``, ``logger``, ``_get_router_metrics()``,
            ``unset_model()``, ``return_response_not_ok()`` and ``run_ep()``.
        retry_policy:
            Optional class providing ``RETRY_WHEN_STATUS``,
            ``TIME_TO_WAIT_SEC`` and ``MAX_RECONNECTIONS``; falls back to the
            endpoint's ``RetryResponse`` attribute and finally to
            :class:`RetryPolicy`.
        """
        self._endpoint = endpoint
        self._default_retry_policy = retry_policy

    # ------------------------------------------------------------------
    # Dynamic lookups (resolved at call time, like the original self.X refs)
    # ------------------------------------------------------------------
    def _logger(self) -> logging.Logger:
        return self._endpoint.logger

    def _http_executor(self) -> Any:
        return self._endpoint.http_executor

    def _get_router_metrics(self) -> Any:
        return self._endpoint._get_router_metrics()

    def _unset_model(
        self, api_model_provider: Any, params: Any, options: Any
    ) -> Any:
        return self._endpoint.unset_model(
            api_model_provider=api_model_provider, params=params, options=options
        )

    def _return_response_not_ok(self, body: Any) -> Any:
        return self._endpoint.return_response_not_ok(body)

    def _rerun_ep(self, **kwargs: Any) -> Any:
        return self._endpoint.run_ep(**kwargs)

    def _call_for_each_user_msg(self) -> bool:
        return self._endpoint.call_for_each_user_msg

    def _retry_policy(self) -> Type:
        policy = getattr(self._endpoint, "RetryResponse", None)
        if policy is not None:
            return policy
        return self._default_retry_policy or RetryPolicy

    # ------------------------------------------------------------------
    # Core dispatch
    # ------------------------------------------------------------------
    def return_response_or_rerun(
        self,
        api_model_provider: Any,
        ep_url: str,
        prompt_str: str,
        orig_params: dict,
        params: dict,
        options: dict,
        reconnect_number: int,
    ) -> Any:
        """
        Send the prepared request to the external service and retry on
        transient failures.

        The method delegates the actual HTTP call to
        :meth:`_http_executor.call_http_request`.  The executor never raises
        for a *non‑OK* HTTP response: it returns the raw ``requests.Response``
        object (carrying ``status_code``) so that this dispatcher owns the
        retry decision.  On success the executor has already parsed the body
        into a ``dict``.

        Behaviour
        ---------
        * **2xx / dict** – returned as‑is (with Prometheus metrics).
        * **retryable status** (see :class:`RetryPolicy.RETRY_WHEN_STATUS`) –
          re‑issued up to ``MAX_RECONNECTIONS`` times, each retry choosing a
          *different* provider (``random_choice``) with an exponential backoff
          delay (``TIME_TO_WAIT_SEC * 2**attempt`` capped at
          ``MAX_BACKOFF_SEC`` plus jitter).
        * **non‑retryable status / exhausted retries / transport error** – an
          ``(error_body, status_code)`` tuple is returned so the caller
          (the Flask registrar) surfaces the *last* provider status to the
          client instead of a masked ``500``.

        Parameters
        ----------
        api_model_provider :
            The :class:`ApiModel` instance describing the target external
            service.
        ep_url : str
            Fully resolved endpoint URL to which the request will be sent.
        prompt_str : str
            Prompt text that may be injected into the request body.
        orig_params : Dict
            The original request parameters (kept for possible retry).
        params : Dict
            The processed parameters that will be sent to the external service.
        options : Dict
            Additional options that may influence request handling.
        reconnect_number : int
            Current retry attempt counter.

        Returns
        -------
        Union[Dict, Tuple[dict, int]]
            On success the JSON payload (a ``dict``); on failure a
            ``(error_body, status_code)`` tuple.
        """
        response = None
        error_exc = None
        provider_latency_start = (
            time.time()
        )  # ---- Prometheus: latency timer -----------

        try:
            response = self._http_executor().call_http_request(
                ep_url=ep_url,
                params=params,
                prompt_str=prompt_str,
                api_model_provider=api_model_provider,
                call_for_each_user_msg=self._call_for_each_user_msg(),
            )
        except Exception as e:
            self._logger().error(e)
            error_exc = e

        # ---- Prometheus: record provider latency & error on exception ---------------
        rm_err = self._get_router_metrics()
        if (
            rm_err is not None
            and api_model_provider is not None
            and error_exc is not None
        ):
            try:
                elapsed = time.time() - provider_latency_start
                rm_err.record_provider_latency(
                    provider_type=api_model_provider.api_type,
                    model_name=api_model_provider.name,
                    seconds=elapsed,
                )
                # Classify the error code for connection‑level failures
                err_msg = str(error_exc).lower()
                err_code = "timeout" if "timeout" in err_msg else "connection_error"
                rm_err.record_provider_error(
                    provider_type=api_model_provider.api_type,
                    model_name=api_model_provider.name,
                    error_code=err_code,
                )
            except Exception:  # pylint: disable=broad-exception-caught
                pass  # metrics must never break the request

        self._unset_model(
            api_model_provider=api_model_provider, params=params, options=options
        )

        # ------------------------------------------------------------------
        # Case 1 – transport‑level failure (connection refused, timeout, …).
        # The request body is a replayable JSON payload, so it is safe to
        # retry against the next provider.
        # ------------------------------------------------------------------
        if error_exc is not None:
            next_options = self._failover_options(options, api_model_provider)
            if self._can_failover(
                api_model_provider, next_options, reconnect_number
            ):
                self._log_retry(
                    api_model_provider, reconnect_number, "connection_error"
                )
                self._record_retry(rm_err, api_model_provider, "connection_error")
                time.sleep(self._backoff_delay(reconnect_number))
                return self._rerun_with_options(
                    orig_params=orig_params,
                    next_options=next_options,
                    reconnect_number=reconnect_number,
                )
            # All retries exhausted (or no retry budget) – report the error
            # instead of silently returning ``None`` (which Flask would
            # convert to ``{}`` with HTTP 200).
            if rm_err is not None and api_model_provider is not None:
                self._safe_record(
                    rm_err.record_retry_exhausted,
                    model_name=api_model_provider.name,
                    last_error_code="connection_error",
                )
            return self._return_response_not_ok(error_exc)

        if not response:
            self._logger().error("Provider returned no response")
            return self._return_response_not_ok("Provider returned no response")

        # ------------------------------------------------------------------
        # Case 2 – success (2xx): the executor already parsed the body into a
        # dict.  Record metrics and return it.
        # ------------------------------------------------------------------
        if isinstance(response, dict):
            if rm_err is not None and api_model_provider is not None:
                self._safe_record(
                    rm_err.record_provider_latency,
                    provider_type=api_model_provider.api_type,
                    model_name=api_model_provider.name,
                    seconds=time.time() - provider_latency_start,
                )
                self._record_usage_tokens(rm_err, api_model_provider, response)
            return response

        # ------------------------------------------------------------------
        # Case 3 – non‑OK provider response (raw object with ``status_code``).
        # ------------------------------------------------------------------
        status_code = int(getattr(response, "status_code", 500))
        retryable = self._is_retryable_status(status_code)
        self._log_provider_error(response, status_code, api_model_provider)

        next_options = self._failover_options(options, api_model_provider)
        if retryable and self._can_failover(
            api_model_provider, next_options, reconnect_number
        ):
            self._log_retry(api_model_provider, reconnect_number, status_code)
            if rm_err is not None and api_model_provider is not None:
                self._safe_record(
                    rm_err.record_provider_latency,
                    provider_type=api_model_provider.api_type,
                    model_name=api_model_provider.name,
                    seconds=time.time() - provider_latency_start,
                )
                self._safe_record(
                    rm_err.record_provider_error,
                    provider_type=api_model_provider.api_type,
                    model_name=api_model_provider.name,
                    error_code=str(status_code),
                )
                self._record_retry(rm_err, api_model_provider, status_code)
            time.sleep(self._backoff_delay(reconnect_number))
            return self._rerun_with_options(
                orig_params=orig_params,
                next_options=next_options,
                reconnect_number=reconnect_number,
            )

        # Non‑retryable status, or all retries exhausted → return the last
        # provider status to the client (no masked 500).
        if rm_err is not None and api_model_provider is not None:
            self._safe_record(
                rm_err.record_provider_latency,
                provider_type=api_model_provider.api_type,
                model_name=api_model_provider.name,
                seconds=time.time() - provider_latency_start,
            )
            self._safe_record(
                rm_err.record_provider_error,
                provider_type=api_model_provider.api_type,
                model_name=api_model_provider.name,
                error_code=str(status_code),
            )
            if retryable:
                self._safe_record(
                    rm_err.record_retry_exhausted,
                    model_name=api_model_provider.name,
                    last_error_code=str(status_code),
                )
        return self._build_provider_error(response, status_code, api_model_provider)

    # ------------------------------------------------------------------
    # Streaming dispatch (with provider failover)
    # ------------------------------------------------------------------
    def stream_or_rerun(
        self,
        *,
        api_model_provider: Any,
        ep_url: str,
        params: Dict[str, Any],
        options: Optional[Dict[str, Any]],
        stream_type: Any,
        orig_params: Optional[Dict[str, Any]] = None,
        reconnect_number: int = 0,
    ) -> Any:
        """
        Start a streaming request and fail over when the provider refuses it.

        The first chunk is pulled eagerly: a provider that cannot serve the
        model answers with an error status *before* producing any content, and
        only at that point the request can still be replayed on another
        provider of the model - and afterwards on its ``fallback_model`` -
        without the client ever seeing a truncated response.

        Parameters
        ----------
        api_model_provider :
            Provider the stream was opened against.
        ep_url : str
            Resolved provider endpoint.
        params : Dict[str, Any]
            Processed payload of the current attempt.
        options : Optional[Dict[str, Any]]
            Request options (carry the already attempted providers).
        stream_type :
            The resolved :class:`StreamConversion` of this attempt.
        orig_params : Optional[Dict[str, Any]], default ``None``
            Original client payload used to replay the request.
        reconnect_number : int, default ``0``
            Current attempt counter.

        Returns
        -------
        Iterable[bytes]
            The stream for the client.  When no provider can serve the request
            it carries a single error chunk, just like a provider error that
            happens while a stream is being consumed.
        """
        try:
            # A provider answers the stream request *before* the first chunk
            # is produced, so both opening the stream and pulling that chunk
            # can still fail the attempt - and both are safe to replay.
            stream = self._http_executor().stream_response(
                ep_url=ep_url,
                params=params,
                options=options,
                stream_type=stream_type,
                api_model_provider=api_model_provider,
            )
            first_chunk = next(stream)
        except StopIteration:
            return iter(())
        except ProviderStreamError as exc:
            return self._stream_failover(
                exc=exc,
                api_model_provider=api_model_provider,
                options=options,
                stream_type=stream_type,
                orig_params=orig_params if orig_params is not None else params,
                reconnect_number=reconnect_number,
            )

        def _chained() -> Iterator[bytes]:
            yield first_chunk
            yield from stream

        return _chained()

    def _stream_failover(
        self,
        *,
        exc: ProviderStreamError,
        api_model_provider: Any,
        options: Optional[Dict[str, Any]],
        stream_type: Any,
        orig_params: Dict[str, Any],
        reconnect_number: int,
    ) -> Any:
        """
        Rotate to another provider after a rejected stream, or give up.

        The provider lock was already released while the stream generator
        unwound, so only the bookkeeping (attempted provider, metrics, backoff)
        and the decision “another provider / fallback model or report the
        error” are left here.
        """
        self._logger().error(
            "Provider request failed: HTTP %s — %s",
            exc.status_code,
            exc.message,
        )

        rm = self._get_router_metrics()
        if rm is not None and api_model_provider is not None:
            self._safe_record(
                rm.record_provider_error,
                provider_type=getattr(api_model_provider, "api_type", "unknown"),
                model_name=api_model_provider.name,
                error_code=str(exc.status_code),
            )

        next_options = self._failover_options(options, api_model_provider)
        if not self._can_failover(
            api_model_provider, next_options, reconnect_number
        ):
            return self._stream_error_iter(exc, stream_type)

        self._log_retry(api_model_provider, reconnect_number, exc.status_code)
        self._record_retry(rm, api_model_provider, exc.status_code)

        time.sleep(self._backoff_delay(reconnect_number))

        return self._rerun_with_options(
            orig_params=orig_params,
            next_options=next_options,
            reconnect_number=reconnect_number,
        )

    @staticmethod
    def _stream_error_iter(
        exc: ProviderStreamError, stream_type: Any
    ) -> Iterator[bytes]:
        """
        Build the final error stream in the format the client expects.

        Mirrors the error chunk emitted by the per-format generators of
        :class:`~llm_router_api.core.stream_handler.StreamHandler`: NDJSON for
        the OpenAI→Ollama conversion, server-sent events otherwise.
        """
        payload = json.dumps({"error": exc.message})
        if stream_type is StreamConversion.OPENAI_TO_OLLAMA:
            chunk = (payload + "\n").encode("utf-8")
        else:
            chunk = f"data: {payload}\n\n".encode("utf-8")

        def _iter() -> Iterator[bytes]:
            yield chunk

        return _iter()

    # ------------------------------------------------------------------
    # Retry helpers
    # ------------------------------------------------------------------
    def _can_retry(self, reconnect_number: int) -> bool:
        """Return ``True`` when a retry budget remains."""
        max_reconn = self._retry_policy().MAX_RECONNECTIONS
        return bool(reconnect_number < max_reconn)

    def _log_retry(
        self, api_model_provider: Any, reconnect_number: int, reason: Any
    ) -> None:
        provider_id = (
            getattr(api_model_provider, "id", "unknown")
            if api_model_provider is not None
            else "unknown"
        )
        self._logger().warning(
            " Provider %s responded with %s. Retrying %d/%d.",
            provider_id,
            reason,
            reconnect_number,
            self._retry_policy().MAX_RECONNECTIONS,
        )

    def _backoff_delay(self, attempt: int) -> float:
        """
        Compute the backoff delay for a given retry *attempt* (0‑based).

        Exponential backoff: ``min(TIME_TO_WAIT_SEC * 2**attempt,
        MAX_BACKOFF_SEC)`` plus a small uniform jitter to avoid a
        thundering herd of simultaneous retries.
        """
        policy = self._retry_policy()
        base = float(getattr(policy, "TIME_TO_WAIT_SEC", TIME_TO_WAIT_SEC))
        cap = float(getattr(policy, "MAX_BACKOFF_SEC", MAX_BACKOFF_SEC))
        delay: float = float(min(base * (2 ** max(0, attempt)), cap))
        delay += float(random.uniform(0.0, base))
        return delay

    def _is_retryable_status(self, status_code: int) -> bool:
        """
        Return ``True`` when *status_code* should move the request on.

        By default every error status qualifies - an error returned by one
        provider says nothing about the others.  Endpoints that want the
        historical, allow-list behaviour set ``RETRY_ON_ANY_ERROR_STATUS =
        False`` on their ``RetryResponse``.
        """
        if status_code < 400:
            return False
        policy = self._retry_policy()

        if policy.RETRY_ON_ANY_ERROR_STATUS:
            return True

        return status_code in policy.RETRY_WHEN_STATUS

    def _failover_options(
        self, options: Optional[Dict[str, Any]], api_model_provider: Any
    ) -> Dict[str, Any]:
        """
        Build the options of the next attempt of the same request.

        The provider that just failed is recorded as attempted, which makes
        :class:`~llm_router_api.core.model_handler.ModelHandler` drop it from
        the candidates, and ``random_choice`` is set so the remaining providers
        are spread instead of always taking the first one.
        """
        next_options = with_attempted_provider(options, api_model_provider)
        next_options["random_choice"] = True
        return next_options

    def _can_failover(
        self,
        api_model_provider: Any,
        next_options: Dict[str, Any],
        reconnect_number: int,
    ) -> bool:
        """
        Return ``True`` when another attempt still has something to try.

        Retrying is pointless once the attempt budget is exhausted or every
        provider of the model - including the whole ``fallback_model`` chain -
        was already used by this request; the caller then reports the last
        provider error instead of repeating a known failure.
        """
        if not self._can_retry(reconnect_number):
            return False

        handler = getattr(self._endpoint, "_model_handler", None)
        model_name = getattr(api_model_provider, "name", None)
        if handler is None or not model_name:
            # No routing information available (builtin endpoints, unit
            # tests): keep the historical "retry while budget remains".
            return True

        try:
            return bool(
                handler.has_provider_candidates(
                    model_name=model_name, options=next_options
                )
            )
        except Exception:  # pylint: disable=broad-exception-caught
            # intentional: a broken candidate check must not block failover.
            return True

    def _rerun_with_options(
        self,
        orig_params: Optional[Dict[str, Any]],
        next_options: Dict[str, Any],
        reconnect_number: int,
    ) -> Any:
        """Re-issue the endpoint with *next_options* (next provider, attempt+1)."""
        return self._rerun_ep(
            params=orig_params,
            reconnect_number=reconnect_number + 1,
            options=next_options,
        )

    def _record_retry(
        self, rm_err: Any, api_model_provider: Any, status_code: Any
    ) -> None:
        if rm_err is None or api_model_provider is None:
            return
        self._safe_record(
            rm_err.record_retry,
            model_name=api_model_provider.name,
            error_code=str(status_code),
        )

    def _record_usage_tokens(
        self, rm_err: Any, api_model_provider: Any, response: Dict[str, Any]
    ) -> None:
        """Extract and record token usage from an OpenAI/Ollama‑style body."""
        if not isinstance(response, dict):
            return
        usage = response.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if prompt_tokens:
            self._safe_record(
                rm_err.record_tokens,
                model_name=api_model_provider.name,
                direction="input",
                count=prompt_tokens,
                provider_type=api_model_provider.api_type,
            )
        if completion_tokens:
            self._safe_record(
                rm_err.record_tokens,
                model_name=api_model_provider.name,
                direction="output",
                count=completion_tokens,
                provider_type=api_model_provider.api_type,
            )

    @staticmethod
    def _safe_record(fn: Any, *args: Any, **kwargs: Any) -> None:
        """Call a metrics recorder without letting it break the request."""
        try:
            fn(*args, **kwargs)
        except Exception:  # pylint: disable=broad-exception-caught
            pass  # metrics must never break the request

    def _log_provider_error(
        self, response: Any, status_code: int, api_model_provider: Any
    ) -> None:
        """
        Log a non‑OK provider response at ``ERROR`` level (server‑side only;
        the client receives the sanitized body from
        :meth:`_build_provider_error`).
        """
        provider_id = (
            getattr(api_model_provider, "id", "unknown")
            if api_model_provider is not None
            else "unknown"
        )
        try:
            message = self._extract_provider_error_message(response, status_code)
        except Exception:  # pylint: disable=broad-exception-caught
            message = "unavailable"
        self._logger().error(
            "Provider %s returned an error: HTTP %s — %s",
            provider_id,
            status_code,
            message,
        )

    def _build_provider_error(
        self, response: Any, status_code: int, api_model_provider: Any
    ) -> Tuple[Dict[str, Any], int]:
        """
        Build the ``(error_body, status_code)`` pair returned to the client
        when a provider fails with a non‑retryable (or exhausted) status.

        The body shape matches :meth:`EndpointI.return_response_not_ok`
        (``{"error": {...}, "status": False}``) and carries the *provider's*
        status code so the client sees e.g. ``429`` instead of a masked 500.
        """
        message = self._extract_provider_error_message(response, status_code)
        provider_id = (
            getattr(api_model_provider, "id", None)
            if api_model_provider is not None
            else None
        )
        is_provider = provider_id is not None
        error_body = {
            "error": {
                "message": sanitize_error_message(message),
                "type": "api_error" if is_provider else "builtin_error",
                "param": None,
                "code": status_code,
            },
            "status": False,
        }
        return error_body, status_code

    @staticmethod
    def _extract_provider_error_message(response: Any, status_code: int) -> str:
        """
        Derive a human‑readable message from a non‑OK provider response.

        Prefers a JSON ``error``/``message`` field (OpenAI / Ollama / vLLM
        shapes), falls back to the raw text, and finally to a generic
        ``HTTP <status>`` string.
        """
        data = None
        try:
            data = response.json()
        except Exception:  # pylint: disable=broad-exception-caught
            data = None
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message")
                if isinstance(msg, str):
                    return msg
            if isinstance(err, str) and err:
                return err
            for key in ("message", "detail", "error"):
                val = data.get(key)
                if isinstance(val, str) and val:
                    return val
        try:
            text = (response.text or "").strip()
        except Exception:  # pylint: disable=broad-exception-caught
            text = ""
        if text:
            return f"Provider error (HTTP {status_code}): {text[:500]}"
        return f"Provider error (HTTP {status_code})"
