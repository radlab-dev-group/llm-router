"""
Idle monitor module.

This module implements :class:`IdleMonitor`, a utility that runs a
background daemon thread to continuously monitor model usage stored in
Redis.  When a model has been idle longer than a configurable threshold
and its host is currently free, a user‑provided ``send_prompt_callback``
is invoked to issue a keep‑alive prompt.  The implementation is
intentionally lightweight and fully typed so it can be reused across
different services that rely on Redis for state tracking.

Typical usage::

    monitor = IdleMonitor(redis_client, idle_time_seconds=1800,
                         send_prompt_callback=my_prompt_sender)
    monitor.start()
    ...
    monitor.stop()
"""

import time
import redis
import logging
import threading
from typing import Callable, Optional


class IdleMonitor:
    """
    Background monitor that detects idle models and triggers keep‑alive prompts.

    The monitor polls Redis at a configurable interval, identifies models
    whose ``last_used`` timestamp exceeds ``idle_time_seconds`` and whose
    associated host is free, then calls ``send_prompt_callback`` with a
    predefined prompt.  All Redis keys used by the monitor follow the
    ``<model_name>:last_host`` and ``<model_name>:last_used`` naming scheme.

    Parameters
    ----------
    redis_client : redis.Redis
        Active Redis connection used for reading and writing monitor state.
    idle_time_seconds : int, optional
        Minimum number of seconds a model must be idle before a prompt is
        sent.  Default is 3600 (one hour).
    check_interval : float, optional
        Frequency, in seconds, with which Redis is scanned.  Default is 0.1.
    logger : logging.Logger, optional
        Logger instance for diagnostic output; if omitted, a module‑level
        logger is created.
    send_prompt_callback : Callable[[str, str], None], optional
        Function invoked to deliver the keep‑alive prompt.  It receives the
        ``model_name`` and the ``prompt`` string.
    get_last_host_key : Callable[[str], str], optional
        Function that returns the Redis key storing the last host for a model.
        Defaults to ``lambda model: f"{model}:last_host"``.
    get_last_used_key : Callable[[str], str], optional
        Function that returns the Redis key storing the last usage timestamp
        for a model.  Defaults to ``lambda model: f"{model}:last_used"``.
    is_host_free_callback : Callable[[str, str], bool], optional
        Function that determines whether a host is free for a given model.
        It receives ``host`` and ``model_name`` and returns ``True`` if the
        host can accept a new prompt.
    clear_buffers : bool, optional
        If ``True``, all monitor‑related keys are removed from Redis during
        initialization.
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
        Initialise a new :class:`IdleMonitor` instance.

        All arguments are stored as attributes and default callbacks are
        provided when the corresponding user‑supplied callbacks are ``None``.
        The monitor does **not** start automatically; call :meth:`start`
        to begin background processing.

        Parameters
        ----------
        redis_client : redis.Redis
            Redis connection used by the monitoring strategy.
        idle_time_seconds : int
            Minimum idle time (seconds) before a model is considered idle.
        check_interval : float
            How often (seconds) to poll Redis for model state.
        logger : logging.Logger, optional
            Optional logger; defaults to a module‑level logger.
        send_prompt_callback : Callable[[str, str], None], optional
            Callback to send a keep‑alive prompt. Signature
            ``(model_name: str, prompt: str) -> None``.
        get_last_host_key : Callable[[str], str], optional
            Callable returning the Redis key that stores the last host used
            for a given model.
        get_last_used_key : Callable[[str], str], optional
            Callable returning the Redis key that stores the timestamp of the
            last model usage.
        is_host_free_callback : Callable[[str, str], bool], optional
            Callable that checks whether a host is free for a given model.
            Signature ``(host: str, model_name: str) -> bool``.
        clear_buffers : bool, optional
            When ``True``, all monitor‑related keys are removed from Redis at
            construction time.
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

        The thread runs as a daemon; it will automatically terminate when
        the main program exits.  Subsequent calls have no effect if the
        thread is already alive.
        """
        self._thread.start()
        self.logger.debug("[idle-monitor] thread started")

    def stop(self) -> None:
        """
        Stop the monitoring thread.

        This method signals the background loop to exit and then joins
        the thread, ensuring a clean shutdown.  It is primarily intended
        for use in unit tests or graceful application termination.
        """
        self._stop_event.set()
        self._thread.join()
        self.logger.debug("IdleMonitor thread stopped")

    def _clear_buffers(self) -> None:
        """
        Remove all Redis keys used by the idle monitor.

        The method scans Redis for keys matching the ``*:last_host`` and
        ``*:last_used`` patterns and deletes them.  It is safe to call
        repeatedly; missing keys are simply ignored.
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

        The loop iterates until ``self._stop_event`` is set.  For each
        ``:last_used`` key found, it determines whether the associated model
        has been idle for longer than ``idle_time_seconds`` and whether its
        host is free.  If both conditions are met, the configured
        ``send_prompt_callback`` is invoked and the ``last_used`` timestamp is
        refreshed to avoid sending duplicate prompts.
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

                    # Log that the host is free and we will send a prompt
                    host_str = (
                        host.decode("utf-8", errors="ignore")
                        if isinstance(host, (bytes, bytearray))
                        else str(host)
                    )
                    self.logger.debug(
                        f"[idle-monitor] host '{host_str}' is free for model "
                        f"'{model_name}' – raising prompt"
                    )

                    # ---- send keep‑alive prompt ----
                    prompt = "W odpowiedzi wybierz tylko 1 lub 2"
                    self._send_prompt(model_name, prompt)

                    # Log that we have sent the keep‑alive prompt
                    self.logger.debug(
                        f"[idle-monitor] keep‑alive prompt sent to model "
                        f"{model_name} on host '{host_str}'"
                    )

                    # ---- update timestamp to avoid spamming ----
                    # ``key`` may be bytes; ensure we write back using a string key
                    ts_key = (
                        key.decode("utf-8")
                        if isinstance(key, (bytes, bytearray))
                        else key
                    )
                    self.redis_client.set(ts_key, int(time.time()))
            except Exception as exc:
                # pragma: no cover – rarely occurs
                self.logger.exception(f"IdleMonitor error: {exc}")

            time.sleep(self.check_interval)
