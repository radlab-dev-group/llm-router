"""
Idle monitor module.

Provides :class:`IdleMonitor` which runs a background thread to detect
idle models and send a keep‑alive prompt via a configurable callback.
"""

import time
import redis
import logging
import threading
from typing import Callable, Optional


class IdleMonitor:
    """
    Component that monitors model activity and sends keep‑alive prompts.

    The monitor runs in a separate daemon thread, periodically checking
    Redis for models that have been idle longer than ``idle_time_seconds``.
    When such a model is found and its host is free, the configured
    ``send_prompt_callback`` is invoked.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        idle_time_seconds: int = 3600,
        check_interval: float = 0.1,
        logger: Optional[logging.Logger] = None,
        send_prompt_callback: Optional[Callable[[str, str], None]] = None,
        get_last_host_key: Optional[Callable[[str], str]] = None,
        get_last_used_key: Optional[Callable[[str], str]] = None,
        is_host_free_callback: Optional[Callable[[str, str], bool]] = None,
        clear_buffers: bool = False,
    ) -> None:
        """
        Create a new :class:`IdleMonitor`.

        Args:
            redis_client: Redis connection used by the monitoring strategy.
            idle_time_seconds: Minimum idle time (seconds) before a model is
                considered idle.
            check_interval: How often (seconds) to poll Redis for model state.
            logger: Optional logger; defaults to a module‑level logger.
            send_prompt_callback: Callback to send a keep‑alive prompt.
                Signature ``(model_name: str, prompt: str) -> None``.
            get_last_host_key: Callable returning the Redis key that stores the
                last host used for a given model.
            get_last_used_key: Callable returning the Redis key that stores the
                timestamp of the last model usage.
            is_host_free_callback: Callable that checks whether a host is free
                for a given model. Signature ``(host: str, model_name: str) -> bool``.
        """
        self.redis_client = redis_client
        self.idle_time_seconds = idle_time_seconds
        self.check_interval = check_interval
        self.logger = logger or logging.getLogger(__name__)

        # Callbacks – allow avoiding circular imports.
        self._send_prompt = (
            send_prompt_callback if send_prompt_callback else lambda m, p: None
        )
        self._get_last_host_key = (
            get_last_host_key if get_last_host_key else lambda m: f"{m}:last_host"
        )
        self._get_last_used_key = (
            get_last_used_key if get_last_used_key else lambda m: f"{m}:last_used"
        )
        self._is_host_free = (
            is_host_free_callback if is_host_free_callback else lambda h, m: False
        )

        if clear_buffers:
            self._clear_buffers()

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """
        Start the monitoring thread.
        """
        self._thread.start()
        self.logger.debug("[idle-monitor] thread started")

    def stop(self) -> None:
        """
        Stop the monitoring thread (useful in tests).
        """
        self._stop_event.set()
        self._thread.join()
        self.logger.debug("IdleMonitor thread stopped")

    def _clear_buffers(self) -> None:
        """
        Remove all Redis keys used by the idle monitor.
        This scans Redis for keys matching the pattern and deletes them.
        """
        # Patterns for keys used by idle monitor
        patterns = ["*:last_host", "*:last_used"]
        for pattern in patterns:
            for key in self.redis_client.scan_iter(match=pattern):
                self.logger.debug(f"Removing idle monitor key from redis: {key}")
                self.redis_client.delete(key)

    def _run(self) -> None:
        """
        Main monitoring loop executed in the background thread.
        """
        while not self._stop_event.is_set():
            try:
                # Find all keys with the ':last_used' suffix
                pattern = "*:last_used"
                for key in self.redis_client.scan_iter(match=pattern):
                    model_name = key.rsplit(":", 1)[0]

                    ts_raw = self.redis_client.get(key)
                    self.logger.debug(
                        f"[idle-monitor] {model_name} last used timestamp: {ts_raw}"
                    )
                    if ts_raw is None:
                        continue
                    try:
                        last_ts = int(ts_raw)
                    except (ValueError, TypeError):
                        continue

                    idle_seconds = int(time.time()) - last_ts
                    if idle_seconds < self.idle_time_seconds:
                        self.logger.debug(
                            f"[idle-monitor] {model_name} idle_seconds: {idle_seconds}"
                        )
                        continue

                    host_key = key.replace(":last_used", ":last_host")
                    host_raw = self.redis_client.get(host_key)
                    if not host_raw:
                        continue
                    host = host_raw.strip()
                    self.logger.debug(f"[idle-monitor] {model_name} host: {host}")

                    if not self._is_host_free(host, model_name):
                        self.logger.debug(
                            f"[idle-monitor]  {model_name} host: {host} is not free"
                        )
                        continue

                    # Logujemy, że host jest wolny i wyślemy prompt
                    host_str = (
                        host.decode("utf-8", errors="ignore")
                        if isinstance(host, (bytes, bytearray))
                        else str(host)
                    )
                    self.logger.debug(
                        f"[idle-monitor] host '{host_str}' is free for model "
                        f"'{model_name}' – raising prompt"
                    )

                    # ---- wysłanie keep‑alive prompt ----
                    prompt = "W odpowiedzi wybierz tylko 1 lub 2"
                    self._send_prompt(model_name, prompt)

                    # Log that we have sent the keep‑alive prompt
                    self.logger.debug(
                        f"[idle-monitor] keep‑alive prompt sent to model "
                        f"{model_name} on host '{host_str}'"
                    )

                    # ---- aktualizacja timestampu, aby nie spamować ----
                    # ``key`` may be bytes; ensure we write back using a string key
                    ts_key = (
                        key.decode("utf-8")
                        if isinstance(key, (bytes, bytearray))
                        else key
                    )
                    self.redis_client.set(ts_key, int(time.time()))
            except Exception as exc:
                # pragma: no cover – rzadko występuje
                self.logger.exception(f"IdleMonitor error: {exc}")

            time.sleep(self.check_interval)
