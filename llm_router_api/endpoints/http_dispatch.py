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

import time
import logging

from typing import Any, List, Optional, Type

# ---------------------------------------------------------------------------
# Retry policy (moved verbatim from ``EndpointWithHttpRequestI.RetryResponse``)
# ---------------------------------------------------------------------------
# Code - definition
#  * 429 - Too Many Requests (rate limited)
#  * 503 - Service Unavailable
#  * 504 - Gateway Timeout
#  * > 500 - General error
RETRY_WHEN_STATUS: List[int] = [429, 503, 504, 500]
TIME_TO_WAIT_SEC: float = 0.1
MAX_RECONNECTIONS: int = 10


class RetryPolicy:
    """
    Configuration for automatic retry handling when an outbound HTTP
    request fails with a transient error.

    Attributes
    ----------
    RETRY_WHEN_STATUS : List[int]
        HTTP status codes that trigger a retry.  Includes client and
        server error codes that are typically recoverable (e.g. 429,
        503, 504, 500).
    TIME_TO_WAIT_SEC : float
        Number of seconds to wait between successive retry attempts.
    MAX_RECONNECTIONS : int
        Upper bound on how many retry attempts will be made before giving
        up.
    """

    RETRY_WHEN_STATUS = RETRY_WHEN_STATUS
    TIME_TO_WAIT_SEC = TIME_TO_WAIT_SEC
    MAX_RECONNECTIONS = MAX_RECONNECTIONS


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

    def _http_executor(self):
        return self._endpoint._http_executor

    def _get_router_metrics(self):
        return self._endpoint._get_router_metrics()

    def _unset_model(self, api_model_provider, params, options):
        return self._endpoint.unset_model(
            api_model_provider=api_model_provider, params=params, options=options
        )

    def _return_response_not_ok(self, body):
        return self._endpoint.return_response_not_ok(body)

    def _rerun_ep(self, **kwargs):
        return self._endpoint.run_ep(**kwargs)

    def _call_for_each_user_msg(self) -> bool:
        return self._endpoint._call_for_each_user_msg

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
        Send the prepared request to the external service and optionally retry
        on transient failures.

        The method delegates the actual HTTP call to
        :meth:`_http_executor.call_http_request`.  If the response status code
        matches one of the values defined in :class:`RetryPolicy`, the call
        is retried up to ``MAX_RECONNECTIONS`` times with a short pause
        between attempts.

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
        Optional[Union[Dict, requests.Response]]
            The response from the external service, possibly after retries,
            or ``None`` if all attempts fail.
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
        if rm_err is not None and api_model_provider is not None:
            try:
                elapsed = time.time() - provider_latency_start
                rm_err.record_provider_latency(
                    provider_type=api_model_provider.api_type,
                    model_name=api_model_provider.name,
                    seconds=elapsed,
                )
                if error_exc is not None:
                    # Classify the error code for connection-level failures
                    err_msg = str(error_exc).lower()
                    if "timeout" in err_msg:
                        rm_err.record_provider_error(
                            provider_type=api_model_provider.api_type,
                            model_name=api_model_provider.name,
                            error_code="timeout",
                        )
                    else:
                        rm_err.record_provider_error(
                            provider_type=api_model_provider.api_type,
                            model_name=api_model_provider.name,
                            error_code="connection_error",
                        )
            except Exception:  # pylint: disable=broad-exception-caught
                pass  # metrics must never break the request

        self._unset_model(
            api_model_provider=api_model_provider, params=params, options=options
        )

        # If the HTTP call failed completely, report the error instead of silently
        # returning ``None`` (which Flask would convert to ``{}`` with HTTP 200).
        if error_exc is not None:
            return self._return_response_not_ok(error_exc)

        status_code = None
        if response and type(response) not in [dict]:
            status_code = response.status_code
        elif not response:
            status_code = 500
        #
        # print("====" * 20)
        # print(response)
        # print("status_code=", status_code)
        # print("====" * 20)

        if status_code and status_code in self._retry_policy().RETRY_WHEN_STATUS:
            self._logger().warning(
                f" Provider {api_model_provider.id} responded with "
                f"{status_code}. Retrying {reconnect_number}/"
                f"{self._retry_policy().MAX_RECONNECTIONS}."
            )

            # ---- Prometheus: retry metrics ----------------------------
            if (
                status_code != 200
                and rm_err is not None
                and api_model_provider is not None
            ):
                try:
                    rm_err.record_provider_latency(
                        provider_type=api_model_provider.api_type,
                        model_name=api_model_provider.name,
                        seconds=time.time() - provider_latency_start,
                    )
                    rm_err.record_provider_error(
                        provider_type=api_model_provider.api_type,
                        model_name=api_model_provider.name,
                        error_code=str(status_code),
                    )
                    if reconnect_number < self._retry_policy().MAX_RECONNECTIONS:
                        rm_err.record_retry(
                            model_name=api_model_provider.name,
                            error_code=str(status_code),
                        )
                except Exception:  # pylint: disable=broad-exception-caught
                    pass

            if reconnect_number < self._retry_policy().MAX_RECONNECTIONS:
                time.sleep(self._retry_policy().TIME_TO_WAIT_SEC)
                if not options:
                    options = {}
                options["random_choice"] = True

                return self._rerun_ep(
                    params=orig_params,
                    reconnect_number=reconnect_number + 1,
                    options=options,
                )
            # ---- Prometheus: retry exhausted (all retries failed) --------
            if rm_err is not None and api_model_provider is not None:
                try:
                    rm_err.record_retry_exhausted(
                        model_name=api_model_provider.name,
                        last_error_code=str(status_code),
                    )
                    rm_err.record_provider_latency(
                        provider_type=api_model_provider.api_type,
                        model_name=api_model_provider.name,
                        seconds=time.time() - provider_latency_start,
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    pass
            return response

        # ---- Prometheus: successful provider call ------------------------
        if rm_err is not None and api_model_provider is not None:
            try:
                rm_err.record_provider_latency(
                    provider_type=api_model_provider.api_type,
                    model_name=api_model_provider.name,
                    seconds=time.time() - provider_latency_start,
                )
                # Try to extract token usage from response body (OpenAI / Ollama format)
                if isinstance(response, dict):
                    usage = response.get("usage", {})
                    prompt_tokens = usage.get("prompt_tokens")
                    completion_tokens = usage.get("completion_tokens")
                    if prompt_tokens:
                        rm_err.record_tokens(
                            model_name=api_model_provider.name,
                            direction="input",
                            count=prompt_tokens,
                            provider_type=api_model_provider.api_type,
                        )
                    if completion_tokens:
                        rm_err.record_tokens(
                            model_name=api_model_provider.name,
                            direction="output",
                            count=completion_tokens,
                            provider_type=api_model_provider.api_type,
                        )
            except Exception:  # pylint: disable=broad-exception-caught
                pass  # metrics must never break the request

        return response
