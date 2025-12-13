import time
import redis
import logging
import threading
import re
from typing import Callable, Optional

from llm_router_api.core.keep_alive import KeepAlive


class KeepAliveMonitor:
    """
    Keep-alive monitor that owns scheduling state in Redis.

    Scheduling is PER PROVIDER instance, i.e. per (model_name, host).
    keep_alive can be a duration string like: "120s", "45m", "2h".
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        keep_alive: KeepAlive,
        check_interval: float = 1.0,
        logger: Optional[logging.Logger] = None,
        is_host_free_callback: Optional[Callable[[str, str], bool]] = None,
        clear_buffers: bool = False,
        redis_prefix: str = "keepalive",
    ) -> None:
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
        self._thread.start()
        self.logger.debug("[keep-alive] thread started")

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join()
        self.logger.debug("[keep-alive] thread stopped")

    def record_usage(
        self, model_name: str, host: str, keep_alive: Optional[str]
    ) -> None:
        """
        Called by strategy after selecting a provider.

        keep_alive:
          - None / "" / Falsey => do not schedule keep-alive for this provider
          - "120s", "45m", "2h" => schedule wakeups every that many seconds
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
            # not configured => ensure it's not scheduled
            pipe.zrem(self._next_wakeup_zset_key(), member)

        pipe.execute()

    def _member(self, model_name: str, host: str) -> str:
        # delimiter unlikely to appear in host; if it can, we can switch to JSON later
        return f"{model_name}|{host}"

    def _split_member(self, member: str) -> tuple[str, str]:
        model_name, host = member.split("|", 1)
        return model_name, host

    def _provider_hash_key(self, model_name: str, host: str) -> str:
        return f"{self._redis_prefix}:provider:{model_name}:{host}"

    def _next_wakeup_zset_key(self) -> str:
        return f"{self._redis_prefix}:providers:next_wakeup"

    def _clear_buffers(self) -> None:
        for key in self.redis_client.scan_iter(
            match=f"{self._redis_prefix}:provider:*"
        ):
            self.redis_client.delete(key)
        self.redis_client.delete(self._next_wakeup_zset_key())

    def _decode_redis(self, value):
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="ignore")
        return str(value)

    def _parse_duration_seconds(self, value: Optional[str]) -> Optional[int]:
        """
        Accepts "120s", "45m", "2h" (case-insensitive). Returns seconds or None.
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
            self.logger.warning(f"[keep-alive] invalid keep_alive duration: {text}")
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
        while not self._stop_event.is_set():
            try:
                now = int(time.time())

                # providers whose next_wakeup <= now
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
                        # host busy => try again later (do not spam)
                        next_wakeup = now + keep_alive_seconds
                        self.redis_client.zadd(
                            self._next_wakeup_zset_key(), {member: next_wakeup}
                        )
                        continue

                    self.logger.debug(
                        f"[keep-alive] due provider model={model_name} "
                        f"host={host} -> sending prompt"
                    )
                    self._keep_alive.send(model_name=model_name, host=host)

                    # schedule next wakeup
                    next_wakeup = int(time.time()) + keep_alive_seconds
                    self.redis_client.zadd(
                        self._next_wakeup_zset_key(), {member: next_wakeup}
                    )

            except Exception as exc:
                self.logger.exception("KeepAliveMonitor error: %s", exc)

            time.sleep(self.check_interval)
