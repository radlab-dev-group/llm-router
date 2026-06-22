"""
Redis-backed sliding window rate limiter.

Uses sorted sets to track request timestamps per key+IP, enforcing
per-minute rate limits without fixed-window boundary artifacts.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import redis


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

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
        redis_client: redis.Redis | None = None,
        redis_host: str | None = None,
        redis_port: int = 6379,
        redis_db: int = 0,
        redis_password: str | None = None,
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

    def is_allowed(
        self, key_id: str, ip: str, limit: int
    ) -> RateLimitResult:
        """
        Check if a request is within the rate limit.

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
        window_start = now - self.WINDOW
        bucket = f"{self.PREFIX}:{key_id}:{ip}"

        # Remove old entries outside the window
        self._redis.zremrangebyscore(bucket, 0, window_start)

        # Count current entries in window
        current_count = self._redis.zcard(bucket)

        if current_count >= limit:
            # Get the oldest entry to calculate retry_after
            oldest = self._redis.zrange(bucket, 0, 0, withscores=True)
            if oldest:
                oldest_ts = oldest[0][1]
                retry_after = int(oldest_ts + self.WINDOW - now) + 1
                retry_after = max(1, retry_after)
            else:
                retry_after = self.WINDOW
            return RateLimitResult(allowed=False, remaining=0, retry_after=retry_after)

        # Add this request
        member = f"{now}:{uuid.uuid4().hex[:6]}"
        pipe = self._redis.pipeline()
        pipe.zadd(bucket, {member: now})
        pipe.expire(bucket, self.WINDOW + 1)
        pipe.execute()

        remaining = limit - current_count - 1
        return RateLimitResult(allowed=True, remaining=remaining, retry_after=0)
