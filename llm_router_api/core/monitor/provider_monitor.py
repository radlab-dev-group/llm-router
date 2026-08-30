"""
Provider monitoring module.

Implements a background thread that periodically checks the health of each
registered LLM provider and records its availability in Redis.  The module
offers a thin wrapper class :class:`ProviderMonitorWrapper` that isolates the
application code from the concrete Redis implementation.
"""

import json
import logging
import requests
import threading

from typing import Dict, List, Optional

try:
    import redis
except ImportError:
    raise RuntimeError("Redis is not available. Please install it first.") from None


class RedisProviderMonitor:
    """
    Background thread that periodically checks the health of each known provider
    and stores its availability in Redis.

    For every model a separate Redis hash ``availability:<model_name>`` is
    maintained where each field is the provider ``id`` and the value is
    ``'true'`` (available) or ``'false'`` (unreachable).  A provider is
    marked unavailable only after ``max_consecutive_failures`` pings fail in
    a row (hysteresis), so a single slow/busy ping does not kick a live host
    out of the pool; one successful ping restores it immediately.  The
    monitor runs continuously until :meth:`stop` is called.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        check_interval: float = 30,
        clear_buffers: bool = False,
        logger: Optional[logging.Logger] = None,
        check_timeout: float = 2.0,
        max_consecutive_failures: int = 2,
    ) -> None:
        """
        Initialize the monitor and start its background thread.

        Parameters
        ----------
        redis_client : redis.Redis
            Connected Redis client used for storing provider status.
        check_interval : float, optional
            Seconds between successive health‑check cycles (default: 30).
        clear_buffers : bool, optional
            If ``True``, remove all existing monitoring keys from Redis on
            start.
        logger : logging.Logger, optional
            Logger instance; if omitted, a module‑level logger is created.
        check_timeout : float, optional
            Per‑provider ping timeout in seconds (default: 2.0).  Kept short
            so a hanging host cannot stall the whole health‑check cycle.
        max_consecutive_failures : int, optional
            Number of **consecutive** failed pings required before a
            provider is marked unavailable (hysteresis, default: 2).  A
            single slow/busy ping therefore does not kick a live provider
            out of the active pool; one successful ping resets the counter.
        """

        self.logger = logger or logging.getLogger(__name__)

        self._redis_client = redis_client
        if clear_buffers:
            self._clear_buffers()

        self._check_interval = check_interval
        self._check_timeout = check_timeout
        self._max_consecutive_failures = max(1, int(max_consecutive_failures))
        # provider id -> number of consecutive failed pings (hysteresis).
        self._consecutive_failures: Dict[str, int] = {}
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def check_interval(self):
        """
        Return the current health‑check interval in seconds.
        """

        return self._check_interval

    def stop(self) -> None:
        """
        Signal the background thread to stop and wait for it to finish.

        The method sets an internal event and joins the thread with a short
        timeout to ensure a clean shutdown.
        """
        self._stop_event.set()
        self._thread.join(timeout=1)

    def add_providers(self, model_name: str, providers: List[Dict]) -> None:
        """
        Register providers for a model.

        Called once per model (the first time
        :meth:`FirstAvailableStrategy.get_provider` is invoked).  The method
        stores the providers list in Redis for monitoring and performs an
        immediate health‑check for each provider.

        Parameters
        ----------
        model_name : str
            Name of the model to which the providers belong.
        providers : List[Dict]
            List of provider configuration dictionaries.
        """
        providers_key = self._monitor_model_key(model_name=model_name)
        if self._redis_client.exists(providers_key):
            return

        avail_key = f"{self._availability_key()}:{model_name}"

        for provider in providers:
            provider_json = json.dumps(provider)
            self._redis_client.sadd(providers_key, provider_json)
            self._check_and_update_status(provider, avail_key)

    def get_providers(
        self, model_name: str, only_active: bool = False
    ) -> List[Dict]:
        """
        Retrieve the list of providers that were registered for *model_name*.

        Parameters
        ----------
        model_name : str
            Name of the model whose providers should be returned.
        only_active : bool, optional
            If ``True`` return only providers that are currently marked as
            available (i.e. the value stored in the ``availability:<model_name>``
            hash is ``'true'``).  If ``False`` (default) return all registered
            providers regardless of their current health status.

        Returns
        -------
        List[Dict]
            List of provider dictionaries.
        """
        providers_key = self._monitor_model_key(model_name=model_name)

        try:
            providers_json = self._redis_client.smembers(providers_key)
        except Exception:
            # Redis problem – treat as no providers
            return []

        providers = [json.loads(p) for p in providers_json]

        if only_active:
            avail_key = f"availability:{model_name}"
            try:
                availability = self._redis_client.hgetall(avail_key)
            except Exception:
                availability = {}

            # Keep only providers whose status is 'true'
            providers = [
                p
                for p in providers
                if availability.get(p.get("id"), "false") == "true"
            ]

        return providers

    @staticmethod
    def _monitor_key() -> str:
        """
        Base Redis key used for storing provider sets.
        """

        return "monitor:providers"

    def _monitor_model_key(self, model_name: str) -> str:
        """
        Redis key for the set of providers belonging to *model_name*.
        """

        return f"{self._monitor_key()}:{model_name}"

    @staticmethod
    def _availability_key() -> str:
        """
        Base Redis key used for availability hashes.
        """

        return "availability"

    def _run(self) -> None:
        """
        Background loop that periodically checks provider health.

        The loop iterates over all registered model keys, loads the associated
        providers, performs health checks via :meth:`_check_and_update_status`,
        and then sleeps for ``self._check_interval`` seconds.  Any unexpected
        exception is logged but does not terminate the thread.
        """
        while not self._stop_event.is_set():
            try:
                keys = self._redis_client.keys(f"{self._monitor_key()}:*")
            except Exception as e:
                self.logger.error(e)
                self._stop_event.wait(self._check_interval)
                continue

            self.logger.debug("[provider-monitor] keys to check: %s", keys)
            for providers_key in keys:
                # Extract model name from key
                model_name = providers_key.replace(f"{self._monitor_key()}:", "")
                avail_key = f"{self._availability_key()}:{model_name}"

                # Load providers from Redis
                try:
                    providers_json = self._redis_client.smembers(providers_key)
                    providers = [json.loads(p) for p in providers_json]
                except Exception as e:
                    self.logger.error(e)
                    continue

                for provider in providers:
                    # Use the shared helper to perform the health‑check
                    self._check_and_update_status(provider, avail_key)

            self._stop_event.wait(self._check_interval)

    def _clear_buffers(self) -> None:
        """
        Remove all monitoring data from Redis.

        Deletes:
        - Provider registration sets ``monitor:providers:<model>``.
        - Availability hashes ``availability:<model>``.
        """
        try:
            # Delete provider registration keys
            provider_keys = self._redis_client.keys(f"{self._monitor_key()}:*")
            if provider_keys:
                self._redis_client.delete(*provider_keys)

            # Delete availability hashes
            availability_keys = self._redis_client.keys(
                f"{self._availability_key()}:*"
            )
            if availability_keys:
                self._redis_client.delete(*availability_keys)
        except Exception as e:
            self.logger.error(f"Failed to clear Redis buffers: {e}")

    #: Real health‑check ping path per provider ``api_type``.
    #:
    #: A lightweight, provider‑specific endpoint is preferred over ``/``
    #: (which many servers answer with an HTML page or ``405``):
    #:
    #: * ``vllm``      → ``/health``
    #: * ``ollama``    → ``/api/version``
    #: * ``openai``    → ``/v1/models`` (OpenAI‑compatible)
    #: * ``lmstudio``  → ``/v1/models`` (OpenAI‑compatible)
    #: * ``anthropic`` → ``/v1/models``
    PING_PATHS = {
        "vllm": "/health",
        "ollama": "/api/version",
        "openai": "/v1/models",
        "lmstudio": "/v1/models",
        "anthropic": "/v1/models",
    }
    DEFAULT_PING_PATH = "/"

    #: Generic probe paths tried when the ``api_type``‑specific path is
    #: **not implemented** by the server (``404``/``405``).  A live
    #: OpenAI‑compatible endpoint is a strong signal that the host serves
    #: LLM traffic even when its advertised ``api_type`` (e.g. ``vllm``)
    #: is a mislabel — the first 2xx/3xx answer wins.
    FALLBACK_PING_PATHS: List[str] = ["/v1/models", "/api/version", "/"]

    @classmethod
    def _ping_path(cls, api_type: Optional[str]) -> str:
        """Return the ping path for an ``api_type`` (``/`` when unknown)."""
        if not api_type:
            return cls.DEFAULT_PING_PATH
        return cls.PING_PATHS.get(
            str(api_type).strip().lower(), cls.DEFAULT_PING_PATH
        )

    @classmethod
    def _ping_candidates(cls, api_type: Optional[str]) -> List[str]:
        """
        Ordered list of probe paths for *api_type*.

        The type‑specific path comes first; the generic
        :data:`FALLBACK_PING_PATHS` follow (deduplicated) so a server that
        simply lacks the specific health endpoint is still detected.
        """
        first = cls._ping_path(api_type)
        candidates = [first]
        for path in cls.FALLBACK_PING_PATHS:
            if path not in candidates:
                candidates.append(path)
        return candidates

    @staticmethod
    def _diagnose_status(status_code: int) -> str:
        """
        Map a non‑OK ping status code to a short diagnostic label.

        ``401``/``403`` → ``auth_error`` (token missing/expired/wrong),
        ``404`` → ``not_found`` (wrong path or host), other 4xx →
        ``client_error_<code>``, 5xx → ``server_error_<code>``.
        """
        if status_code in (401, 403):
            return "auth_error"
        if status_code == 404:
            return "not_found"
        if status_code < 500:
            return f"client_error_{status_code}"
        return f"server_error_{status_code}"

    def _check_and_update_status(self, provider: Dict, avail_key: str) -> None:
        """
        Perform a health‑check for a single provider and store the result
        in the ``availability`` hash.

        Availability contract: a provider is **available only on a 2xx/3xx
        ping response**.  Any 4xx (e.g. ``401``/``403`` broken auth, ``404``
        wrong endpoint) marks it *unavailable* — such a provider would fail
        real requests, so it must stay out of the active pool — with a
        distinct diagnostic label (``auth_error`` vs ``not_found`` vs …)
        stored in the ``availability:reason`` hash for operator triage.

        Parameters
        ----------
        provider : Dict
            Provider definition containing at least ``id`` and ``api_host``.
        avail_key : str
            Redis hash key where the status should be stored
            (e.g. ``availability:<model_name>``).
        """
        provider_id = provider.get("id")
        host = provider.get("api_host")
        if not provider_id or not host:
            return

        # ``.get`` — providers without an ``api_type`` field must not crash
        # the monitor (KeyError used to take the worker down).
        api_type = provider.get("api_type")
        base_url = host.rstrip("/")
        candidates = self._ping_candidates(api_type)

        # Send the provider token when configured: auth‑required providers
        # (OpenAI, Anthropic, …) would otherwise 401 on the ping and be
        # wrongly reported as broken (``auth_error``).
        headers: Dict[str, str] = {}
        api_token = provider.get("api_token")
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        ok = False
        reason = "unreachable"
        last_url = base_url + candidates[0]
        primary_diag: Optional[str] = None
        for path in candidates:
            url = base_url + path
            last_url = url
            try:
                resp = requests.get(
                    url, timeout=self._check_timeout, headers=headers
                )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                # Connection refused / DNS failure / timeout — host is
                # down; further paths would fail identically.
                reason = f"unreachable ({type(exc).__name__})"
                break
            if resp.status_code < 400:
                ok = True
                reason = "ok"
                break
            diag = self._diagnose_status(resp.status_code)
            if primary_diag is None:
                primary_diag = diag
            # 404/405 = "this path is not implemented on that server" —
            # fall back to the next probe path before giving up.
            if resp.status_code in (404, 405):
                continue
            # 401/403 (auth) and other 4xx/5xx are definitive answers
            # about the *server*, not the path — stop probing.
            reason = diag
            break
        else:
            # Every probe path was tried (all 404/405): report the
            # diagnosis of the type‑specific (primary) path.
            reason = primary_diag or "not_found"

        # Hysteresis: a provider is marked unavailable only after
        # ``max_consecutive_failures`` failed pings in a row.  A busy but
        # alive host (slow to accept a *new* connection while serving
        # keep‑alive traffic) must not be kicked out of the pool by a
        # single transient timeout.  One successful ping resets the
        # counter and immediately restores availability.
        if ok:
            self._consecutive_failures[provider_id] = 0
            status = "true"
        else:
            failures = self._consecutive_failures.get(provider_id, 0) + 1
            self._consecutive_failures[provider_id] = failures
            if failures >= self._max_consecutive_failures:
                status = "false"
            else:
                status = None  # keep the last known availability
                reason = (
                    f"{reason} (transient, {failures}/"
                    f"{self._max_consecutive_failures})"
                )

        self.logger.debug(
            "[provider-monitor.status] %s [%s] status=%s reason=%s",
            provider_id,
            last_url,
            status if status is not None else "unchanged",
            reason,
        )

        try:
            if status is not None:
                self._redis_client.hset(avail_key, provider_id, status)
            # Diagnostic label so operators can see *why* a provider was
            # removed from the active pool (auth_error vs not_found vs …).
            self._redis_client.hset(
                f"{self._availability_key()}:reason", provider_id, reason
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Intentionally non‑fatal: a Redis hiccup must not kill the
            # monitor loop — the next cycle retries.
            self.logger.debug("failed to store availability: %s", exc)
