"""
Tests for RedisRateLimiter — verifies atomic Lua script behavior.
"""

from __future__ import annotations

import time

from typing import Any, Dict, List

from llm_router_api.core.auth.rate_limiter import RedisRateLimiter, RateLimitResult


# ---------------------------------------------------------------------------
# FakeRedis mimics Redis sorted-set commands for unit testing without a server.
# ---------------------------------------------------------------------------
class FakeRedis:
    """
    Minimal fake that supports the sorted-set operations used by the rate limiter.
    """

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, float]] = {}  # bucket -> {member: score}
        self._expires: Dict[str, int] = {}
        self._scripts: List[Any] = []

    def zremrangebyscore(
        self, bucket: str, min_score: float, max_score: float
    ) -> int:
        if bucket not in self._data:
            return 0
        before = len(self._data[bucket])
        self._data[bucket] = {
            m: s
            for m, s in self._data[bucket].items()
            if not (min_score <= s <= max_score)
        }
        return before - len(self._data[bucket])

    def zcard(self, bucket: str) -> int:
        if bucket not in self._data:
            return 0
        self._purge_expired(bucket)
        return len(self._data.get(bucket, {}))

    def zrange(self, bucket: str, start: int, stop: int, withscores: bool = False):
        if bucket not in self._data or not self._data[bucket]:
            return []
        items = sorted(self._data[bucket].items(), key=lambda x: x[1])
        sliced = items[start : stop + 1 if stop >= 0 else None]
        if withscores:
            return list(sliced)
        return [m for m, s in sliced]

    def zadd(self, bucket: str, mapping: Dict[str, float]) -> int:
        if bucket not in self._data:
            self._data[bucket] = {}
        new_members = set(mapping.keys()) - set(self._data[bucket].keys())
        self._data[bucket].update(mapping)
        return len(new_members)

    def expire(self, key: str, seconds: int) -> bool:
        self._expires[key] = time.time() + seconds
        return True

    def register_script(self, script_text: str):
        """
        Register a Lua script — stores it for EVAL invocation.
        """

        script = FakeScript(script_text, self)
        self._scripts.append(script)
        return script

    def _purge_expired(self, bucket: str) -> None:
        if bucket in self._expires and time.time() > self._expires[bucket]:
            # Bucket expired — do NOT auto-delete; let the caller handle it.
            pass

    def evalsha(self, sha: str, numkeys: int, *args):
        """
        Fallback for when EVALSHA is not loaded.
        """

        return self._raw_eval(args)

    def _raw_eval(self, args):
        """
        Handle evaluation from register_script wrapper.
        """

        # Find the registered script
        for script in self._scripts:
            result = script.execute(args)
            if result is not None:
                return result
        return []


class FakeScript:
    """
    Minimal Lua evaluator that handles the specific atomic rate-limit script.
    """

    def __init__(self, script_text: str, redis: FakeRedis):
        self._script = script_text
        self._redis = redis

    def execute(self, args):
        """
        Execute the Lua script logic directly in Python (since we can't run Lua).
        """

        # Parse KEYS and ARGV from args
        if not args or len(args) < 4:
            return []

        # The script expects: keys=[bucket], args=[now, window, limit, uuid_part]
        # But register_script wraps it so args become [bucket, now, window, limit, uuid]
        # Let's parse as the actual call does

        # When called via script(keys=[bucket], args=[now, window, limit, uuid])
        # In FakeRedis.register_script + __call__, we need to handle both formats
        return []

    def __call__(self, keys: List[str], args: list):
        """
        Execute the Lua script for this call.
        """

        bucket = keys[0]
        now, window, limit, uuid_part = args[0], args[1], args[2], args[3]

        # Step 1: Remove old entries
        self._redis.zremrangebyscore(bucket, 0, now - window)

        # Step 2: Count current entries
        count = self._redis.zcard(bucket)

        if count >= limit:
            # Denied — calculate retry_after from oldest entry
            oldest = self._redis.zrange(bucket, 0, 0, withscores=True)
            if oldest:
                oldest_ts = oldest[0][1]
                retry_after = int(oldest_ts + window - now)
                retry_after = max(retry_after, 1)
            else:
                retry_after = 1
            return [str(0), str(retry_after)]

        # Step 3: Allow — add this request and set expiry
        member = f"{now}:{uuid_part}"
        self._redis.zadd(bucket, {member: now})
        self._redis.expire(bucket, int(window) + 1)
        remaining = int(limit) - count - 1
        return [str(1), str(remaining)]


# ---------------------------------------------------------------------------
# The rate limiter under test
# ---------------------------------------------------------------------------


class TestRateLimiterAtomicity:
    """
    Verify the Lua-based rate limiter works correctly.
    """

    def setup_method(self) -> None:
        self.fake_redis = FakeRedis()
        self.limiter = RedisRateLimiter(redis_client=self.fake_redis, window=60)

    def test_allows_within_limit(self) -> None:
        """
        Should allow requests within the rate limit.
        """

        result = self.limiter.is_allowed("key1", "10.0.0.1", 5)
        assert result.allowed is True
        assert result.remaining == 4

    def test_denies_over_limit(self) -> None:
        """
        Should deny requests that exceed the rate limit.
        """

        for _ in range(5):
            self.limiter.is_allowed("key2", "10.0.0.1", 5)

        result = self.limiter.is_allowed("key2", "10.0.0.1", 5)
        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after > 0

    def test_separate_keys_have_separate_limits(self) -> None:
        """
        Different key_ids should have independent rate limits.
        """

        for _ in range(3):
            self.limiter.is_allowed("keyA", "10.0.0.1", 5)
        for _ in range(3):
            self.limiter.is_allowed("keyB", "10.0.0.1", 5)

        # Both should still be allowed (only 3/5 used each)
        r_a = self.limiter.is_allowed("keyA", "10.0.0.1", 5)
        r_b = self.limiter.is_allowed("keyB", "10.0.0.1", 5)
        assert r_a.allowed is True
        assert r_b.allowed is True

    def test_separate_ips_have_separate_limits(self) -> None:
        """
        Different client IPs should have independent rate limits.
        """

        for _ in range(3):
            self.limiter.is_allowed("key1", "10.0.0.1", 5)
        for _ in range(3):
            self.limiter.is_allowed("key1", "10.0.0.2", 5)

        # Both should still be allowed (only 3/5 used each)
        r_ip1 = self.limiter.is_allowed("key1", "10.0.0.1", 5)
        r_ip2 = self.limiter.is_allowed("key1", "10.0.0.2", 5)
        assert r_ip1.allowed is True
        assert r_ip2.allowed is True

    def test_retry_after_positive(self) -> None:
        """
        When denied, retry_after should be a positive integer.
        """

        for _ in range(5):
            self.limiter.is_allowed("key3", "10.0.0.1", 5)

        result = self.limiter.is_allowed("key3", "10.0.0.1", 5)
        assert result.allowed is False
        assert isinstance(result.retry_after, int)
        assert result.retry_after > 0


class TestRateLimiterLuaScript:
    """
    Verify that the Lua script is registered and used.
    """

    def test_script_is_registered(self) -> None:
        """
        The atomic Lua script should be registered on first use.
        """

        self.fake_redis = FakeRedis()
        limiter = RedisRateLimiter(redis_client=self.fake_redis, window=60)

        # Before any call, _atomic_script is None
        assert limiter._atomic_script is None

        # After first call, it should be registered
        limiter.is_allowed("test", "1.2.3.4", 10)
        assert limiter._atomic_script is not None


class TestRateLimitResult:
    """
    Verify RateLimitResult dataclass.
    """

    def test_allowed_result(self) -> None:
        result = RateLimitResult(allowed=True, remaining=5, retry_after=0)
        assert result.allowed is True
        assert result.remaining == 5
        assert result.retry_after == 0

    def test_denied_result(self) -> None:
        result = RateLimitResult(allowed=False, remaining=0, retry_after=30)
        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after == 30
