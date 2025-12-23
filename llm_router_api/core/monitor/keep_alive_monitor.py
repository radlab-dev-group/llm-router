"""
Keep‑alive monitor module.

Runs a background thread that periodically triggers keep‑alive requests for
registered ``(model, host)`` pairs.  The logic is unchanged – only the
docstrings and comments have been translated to English.
"""

import re
import time
import redis
import logging
import threading

from typing import Callable, Optional

from llm_router_api.core.monitor.keep_alive import KeepAlive
from llm_router_api.base.constants import KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS


class KeepAliveMonitor:
    """
    Keep‑alive monitor that owns the scheduling state in Redis.

    Scheduling is **per provider instance**, i.e., per ``(model_name, host)`` pair.
    ``keep_alive`` can be a duration string such as ``"120s"``, ``"45m"``,
    or ``"2h"``.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        keep_alive: KeepAlive,
        check_interval: float = KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS,
        logger: Optional[logging.Logger] = None,
        is_host_free_callback: Optional[Callable[[str, str], bool]] = None,
        clear_buffers: bool = False,
        redis_prefix: str = "keepalive",
    ) -> None:
        """
        Initialize the monitor.

        Parameters
        ----------
        redis_client: redis.Redis
            Redis client used for scheduling data.
        keep_alive: KeepAlive
            Instance used to actually send keep‑alive requests.
        check_interval: float, optional
            How often (seconds) the monitor checks for due providers.
        logger: logging.Logger, optional
            Logger instance; defaults to a module‑level logger.
        is_host_free_callback: Callable[[str, str], bool], optional
            Callback that determines whether a host is free for a model.
        clear_buffers: bool, optional
            If ``True``, clear all monitor‑related keys in Redis on start.
        redis_prefix: str, optional
            Prefix used for monitor keys in Redis.
        """
        self.redis_client = redis_client
        self._keep_alive = keep_alive

        self.check_interval = check_interval
        self.logger = logger or logging.getLogger(__name__)
        self._is_host_free = (
            is_host_free_callback if is_host_free_callback else (lambda h, m: False)
        )
        self._redis_prefix = redis_prefix

        if clear_buffers:
            self._clear_buffers()

        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        """
        Start the background monitor thread.
        """
        self._thread.start()
        self.logger.debug("[keep-alive-monitor] thread started")

    def stop(self) -> None:
        """
        Stop the background monitor thread and wait for it to finish.
        """
        self._stop_event.set()
        self._thread.join()
        self.logger.debug("[keep-alive-monitor] thread stopped")

    def record_usage(
        self, model_name: str, host: str, keep_alive: Optional[str]
    ) -> None:
        """
        Record that a provider should receive keep‑alive requests.

        ``keep_alive`` can be:

        * falsy (``None``, ``""``, ``False``) – no keep‑alive scheduled.
        * a duration string like ``"120s"``, ``"45m"``, ``"2h"`` – schedule
          periodic wake‑ups accordingly.

        Parameters
        ----------
        model_name: str
            Logical model name.
        host: str
            Host address.
        keep_alive: str | None
            Duration specification or falsy value.
        """
        if not keep_alive or not model_name or not host:
            return

        seconds = self._parse_duration_seconds(keep_alive)
        provider_key = self._provider_hash_key(model_name, host)
        member = self._member(model_name, host)

        pipe = self.redis_client.pipeline()
        pipe.hset(
            provider_key,
            mapping={
                "model_name": model_name,
                "host": host,
                "keep_alive_seconds": str(seconds or 0),
            },
        )

        if seconds and seconds > 0:
            next_wakeup = int(time.time()) + int(seconds)
            pipe.zadd(self._next_wakeup_zset_key(), {member: next_wakeup})
        else:
            # Not configured – ensure the provider is not scheduled
            pipe.zrem(self._next_wakeup_zset_key(), member)

        # -----------------------------------------------------------------
        # Keep a set of *all* hosts that have keep‑alive configured
        # for this model.  This set is used only for bookkeeping – the
        # actual scheduling still happens via the sorted‑set above.
        hosts_set_key = f"{self._redis_prefix}:model:{model_name}:hosts"
        pipe.sadd(hosts_set_key, host)

        pipe.execute()

    @staticmethod
    def _member(model_name: str, host: str) -> str:
        """
        Create a Redis sorted‑set member identifier.
        """
        return f"{model_name}|{host}"

    @staticmethod
    def _split_member(member: str) -> tuple[str, str]:
        """
        Split a member identifier back into ``(model_name, host)``.
        """
        model_name, host = member.split("|", 1)
        return model_name, host

    def _provider_hash_key(self, model_name: str, host: str) -> str:
        """
        Redis hash key storing provider metadata.
        """
        return f"{self._redis_prefix}:provider:{model_name}:{host}"

    def _next_wakeup_zset_key(self) -> str:
        """
        Redis sorted‑set key holding the next wake‑up timestamps.
        """
        return f"{self._redis_prefix}:providers:next_wakeup"

    def _clear_buffers(self) -> None:
        """
        Delete all monitor‑related keys from Redis.
        """
        for key in self.redis_client.scan_iter(
            match=f"{self._redis_prefix}:provider:*"
        ):
            self.logger.debug(f"[keep-alive-monitor] deleting {key}")
            self.redis_client.delete(key)

        self.logger.debug(
            f"[keep-alive-monitor] deleting {self._next_wakeup_zset_key()}"
        )
        self.redis_client.delete(self._next_wakeup_zset_key())

    @staticmethod
    def _decode_redis(value):
        """
        Decode a Redis value to a Python string (or ``None``).
        """
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="ignore")
        return str(value)

    def _parse_duration_seconds(self, value: Optional[str]) -> Optional[int]:
        """
        Parse a duration string like ``"120s"``, ``"45m"``, ``"2h"``.

        Returns the number of seconds or ``None`` if parsing fails.
        """
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8", errors="ignore")

        text = str(value).strip()
        if not text:
            return None

        m = re.fullmatch(r"(?i)\s*(\d+)\s*([smh])\s*", text)
        if not m:
            self.logger.warning(
                f"[keep-alive-monitor] invalid keep_alive duration: {text}"
            )
            return None

        amount = int(m.group(1))
        unit = m.group(2).lower()

        if unit == "s":
            return amount
        if unit == "m":
            return amount * 60
        if unit == "h":
            return amount * 3600

        return None

    def _run(self) -> None:
        """
        Background loop that triggers keep‑alive requests when due.
        """
        while not self._stop_event.is_set():
            try:
                now = int(time.time())

                # Providers whose next_wakeup <= now
                due = self.redis_client.zrangebyscore(
                    self._next_wakeup_zset_key(),
                    min=0,
                    max=now,
                )

                for raw_member in due:
                    member = self._decode_redis(raw_member)
                    if not member or "|" not in member:
                        continue

                    model_name, host = self._split_member(member)
                    provider_key = self._provider_hash_key(model_name, host)

                    keep_alive_seconds_raw = self.redis_client.hget(
                        provider_key, "keep_alive_seconds"
                    )
                    keep_alive_seconds_txt = (
                        self._decode_redis(keep_alive_seconds_raw) or "0"
                    )

                    try:
                        keep_alive_seconds = int(keep_alive_seconds_txt)
                    except (ValueError, TypeError):
                        keep_alive_seconds = 0

                    if keep_alive_seconds <= 0:
                        self.redis_client.zrem(self._next_wakeup_zset_key(), member)
                        continue

                    if not self._is_host_free(host, model_name):
                        # Host busy – reschedule later (do not spam)
                        next_wakeup = now + keep_alive_seconds
                        self.redis_client.zadd(
                            self._next_wakeup_zset_key(), {member: next_wakeup}
                        )
                        continue

                    self.logger.debug(
                        f"[keep-alive-monitor.sending_prompt] model={model_name} "
                        f"host={host}"
                    )
                    self._keep_alive.send(model_name=model_name, host=host)

                    # Schedule the next wake‑up
                    next_wakeup = int(time.time()) + keep_alive_seconds
                    self.redis_client.zadd(
                        self._next_wakeup_zset_key(), {member: next_wakeup}
                    )

            except Exception as exc:
                self.logger.exception("KeepAliveMonitor error: %s", exc)

            time.sleep(self.check_interval)
