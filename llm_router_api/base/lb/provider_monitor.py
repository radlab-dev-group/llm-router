import json
import logging
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
    Background thread that periodically checks the health of each known
    provider and stores its availability in Redis.

    For each model a separate Redis hash ``availability:<model_name>`` is
    maintained where each field is the provider ``id`` and the value is
    ``'true'`` (available) or ``'false'`` (unreachable).
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        check_interval: float = 30,
        clear_buffers: bool = False,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if not REDIS_IS_AVAILABLE:
            raise RuntimeError("Redis is not available. Please install it first.")

        self.logger = logger

        self._redis_client = redis_client
        if clear_buffers:
            self._clear_buffers()

        self._check_interval = check_interval
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the background thread to stop and wait for it to finish."""
        self._stop_event.set()
        self._thread.join(timeout=1)

    def add_providers(self, model_name: str, providers: List[Dict]) -> None:
        """
        Register providers for a model. Called once per model (the first
        time :meth:`FirstAvailableStrategy.get_provider` is invoked).
        Stores the providers list in Redis for monitoring and checks their
        status immediately.
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

            # Keep only providers whose status is 'true' (or missing → assume unavailable)
            providers = [
                p
                for p in providers
                if availability.get(p.get("id"), "false") == "true"
            ]

        return providers

    @staticmethod
    def _monitor_key():
        return "monitor:providers"

    def _monitor_model_key(self, model_name: str):
        return f"{self._monitor_key()}:{model_name}"

    @staticmethod
    def _availability_key():
        return "availability"

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                keys = self._redis_client.keys(f"{self._monitor_key()}:*")
            except Exception:
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
                except Exception:
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
            # Log or ignore errors – the caller can decide how to handle them
            print(f"Failed to clear Redis buffers: {e}")

    def _check_and_update_status(self, provider: Dict, avail_key: str) -> None:
        """
        Perform a health‑check for a single provider and store the result
        in the ``availability`` hash.

        Parameters
        ----------
        provider: Dict
            Provider definition containing at least ``id`` and ``api_host``.
        avail_key: str
            Redis hash key where the status should be stored
            (e.g. ``availability:<model_name>``).
        """
        provider_id = provider.get("id")
        host = provider.get("api_host")
        if not provider_id or not host:
            return

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
