"""
Redis-backed sliding window rate limiter.

Uses sorted sets to track request timestamps per key+IP, enforcing
per-minute rate limits without fixed-window boundary artifacts.
"""

from __future__ import annotations

import time
import uuid
import redis

from typing import Optional
from dataclasses import dataclass


# Atomic Lua script: remove old entries, check the limit, and optionally
# add the request. Returns an array {allowed, remaining_or_oldest_ts}:
#   allowed == 1 -> allowed, remaining is the number
#                   of available slots AFTER this request
#   allowed == 0 -> rejected, remaining = time until refresh
#   (oldest entry + window - now)
_ATOMIC_LUA = """
    local bucket = KEYS[1]
    local now      = tonumber(ARGV[1])
    local window   = tonumber(ARGV[2])
    local limit    = tonumber(ARGV[3])

    -- Usun entry poza oknem
    redis.call('zremrangebyscore', bucket, 0, now - window)

    -- Polacz bierace
    local count = redis.call('zcard', bucket)

    if count >= limit then
        -- Odrzucony — policz retry_after z najstarszego entry.
        -- Uwaga: `zrange ... withscores` zwraca PLASKA tablice
        -- {member, score}, więc score jest w `oldest[2]` (nie `oldest[1][2]`,
        -- co jest drugim znakiem stringa-membera i w Lua daje błąd
        -- "attempt to perform arithmetic on a string value").
        local oldest = redis.call('zrange', bucket, 0, 0, 'withscores')
        -- ZRANGE ... WITHSCORES returns scores as strings in Redis Lua;
        -- coerce explicitly so the arithmetic below is unambiguous.
        local oldest_ts = tonumber(oldest[2])
        local retry_after = math.ceil(oldest_ts + window - now)
        if retry_after < 1 then retry_after = 1 end
        return {0, retry_after}
    end

    -- Dozwolony — dodaj ten request
    local member = now .. ':' .. ARGV[4]
    redis.call('zadd', bucket, now, member)
    redis.call('expire', bucket, window + 1)
    return {1, limit - count - 1}
"""


@dataclass
class RateLimitResult:
    """
    Result of a rate limit check.
    """

    allowed: bool
    remaining: int
    retry_after: int  # seconds until the oldest request in window expires


class RedisRateLimiter:
    """
    Sliding window rate limiter backed by Redis sorted sets.

    Each rate limit bucket is a sorted set where scores are Unix timestamps
    and member values are unique identifiers.  The ``WINDOW`` (default 60 s)
    determines the rate limit window.
    """

    PREFIX = "auth:ratelimit"
    WINDOW = 60  # seconds

    def __init__(
        self,
        redis_client: Optional[redis.Redis] = None,
        redis_host: Optional[str] = None,
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: Optional[str] = None,
        window: int = 60,
    ) -> None:
        if redis_client is not None:
            self._redis = redis_client
        else:
            self._redis = redis.Redis(
                host=redis_host or "127.0.0.1",
                port=redis_port,
                db=redis_db,
                decode_responses=True,
                password=redis_password,
            )
        self.WINDOW = window
        # Register the Lua script once on first use (EVALSHA optimization)
        self._atomic_script: Optional[redis.Script] = None

    def _get_atomic_script(self) -> redis.Script:
        """
        Return a registered EVALSHA-ready Script for the atomic rate-limit logic.
        """

        if self._atomic_script is None:
            self._atomic_script = self._redis.register_script(_ATOMIC_LUA)
        return self._atomic_script

    def is_allowed(self, key_id: str, ip: str, limit: int) -> RateLimitResult:
        """
        Check if a request is within the rate limit.

        Uses an atomic Redis Lua script so that check-then-set cannot be
        interleaved by concurrent requests.

        Parameters
        ----------
        key_id : str
            The API key identifier.
        ip : str
            The client IP address.
        limit : int
            Maximum requests per window.

        Returns
        -------
        RateLimitResult
            Whether the request is allowed and how many are remaining.
        """
        now = time.time()
        bucket = f"{self.PREFIX}:{key_id}:{ip}"

        script = self._get_atomic_script()
        result = script(
            keys=[bucket],
            args=[now, self.WINDOW, limit, uuid.uuid4().hex[:6]],
        )

        # Lua returns {allowed, value} — both are strings in decode_responses=True mode
        allowed = int(result[0]) == 1
        if allowed:
            remaining = int(result[1])
            return RateLimitResult(allowed=True, remaining=remaining, retry_after=0)
        else:
            retry_after = int(result[1])
            return RateLimitResult(
                allowed=False, remaining=0, retry_after=retry_after
            )
