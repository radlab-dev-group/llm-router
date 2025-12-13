"""
Provider monitoring module.

Implements a background thread that periodically checks the health of each
registered LLM provider and records its availability in Redis.  The module
offers a thin wrapper class :class:`ProviderMonitorWrapper` that isolates the
application code from the concrete Redis implementation.
"""

import json
import logging
import time

import requests
import threading

from typing import List, Dict, Optional

try:
    import redis

    REDIS_IS_AVAILABLE = True
except ImportError:
    REDIS_IS_AVAILABLE = False


class RedisProviderMonitor:
    """
    Background thread that periodically checks the health of each known provider
    and stores its availability in Redis.

    For every model a separate Redis hash ``availability:<model_name>`` is
    maintained where each field is the provider ``id`` and the value is
    ``'true'`` (available) or ``'false'`` (unreachable).  The monitor runs
    continuously until :meth:`stop` is called.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        check_interval: float = 30,
        clear_buffers: bool = False,
        logger: Optional[logging.Logger] = None,
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
        """
        if not REDIS_IS_AVAILABLE:
            raise RuntimeError("Redis is not available. Please install it first.")

        self.logger = logger or logging.getLogger(__name__)

        self._redis_client = redis_client
        if clear_buffers:
            self._clear_buffers()

        self._check_interval = check_interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def check_interval(self):
        """Return the current health‑check interval in seconds."""
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
    def _monitor_key():
        """Base Redis key used for storing provider sets."""
        return "monitor:providers"

    def _monitor_model_key(self, model_name: str):
        """Redis key for the set of providers belonging to *model_name*."""
        return f"{self._monitor_key()}:{model_name}"

    @staticmethod
    def _availability_key():
        """Base Redis key used for availability hashes."""
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

            self.logger.debug(f"[monitor] keys to check: {keys}")
            for providers_key in keys:
                # Extract model name from key
                model_name = providers_key.replace(f"{self._monitor_key()}:", "")
                avail_key = f"{self._availability_key()}:{model_name}"

                # Load providers from Redis
                try:
                    providers_json = self._redis_client.smembers(providers_key)
                    providers = [json.loads(p) for p in providers_json]
                except Exception as e:
                    continue

                for provider in providers:
                    # Use the shared helper to perform the health‑check
                    self._check_and_update_status(provider, avail_key)

                self._stop_event.wait(self._check_interval)
            time.sleep(self._check_interval)

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

    def _check_and_update_status(self, provider: Dict, avail_key: str) -> None:
        """
        Perform a health‑check for a single provider and store the result
        in the ``availability`` hash.

        Parameters
        ----------
        provider : dict
            Provider definition containing at least ``id`` and ``api_host``.
        avail_key : str
            Redis hash key where the status should be stored
            (e.g. ``availability:<model_name>``).
        """
        provider_id = provider.get("id")
        host = provider.get("api_host")
        if not provider_id or not host:
            return

        ep_to_call = "/"
        api_type = provider["api_type"]
        if api_type in ["vllm"]:
            ep_to_call = "/health"

        host = host.rstrip("/") + ep_to_call
        try:
            resp = requests.get(host, timeout=1)
            status = "true" if resp.status_code < 500 else "false"
        except Exception:
            status = "false"

        self.logger.debug(
            f"[monitor.provider_status] {provider_id} [{host}] status={status}"
        )

        try:
            self._redis_client.hset(avail_key, provider_id, status)
        except Exception:
            pass
