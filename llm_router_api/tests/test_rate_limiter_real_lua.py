"""
Real-Redis tests for the atomic rate-limit Lua script.

The unit tests in ``test_rate_limiter.py`` use a Python fake that
*re-implements* the Lua logic, so they cannot catch bugs in the Lua script
itself.  These tests execute the actual ``_ATOMIC_LUA`` script against a
live Redis server (e.g. ``docker run -p 16399:6379 redis:7``).

Regression: the reject path used ``oldest[1][2]`` on the flat Lua table
returned by ``ZRANGE ... WITHSCORES`` — an index into the member *string* —
which raises a Lua runtime error on real Redis, turning a rate-limit
rejection (429 + Retry-After) into a 500 error.

The suite skips itself when no Redis server is reachable.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest

import redis

from llm_router_api.core.auth.rate_limiter import RedisRateLimiter

# Candidate test-redis endpoints (disposable container first, then local).
CANDIDATES = [
    ("127.0.0.1", 16399),
    ("127.0.0.1", 6379),
]


def _find_redis():
    for host, port in CANDIDATES:
        try:
            client = redis.Redis(host=host, port=port, socket_connect_timeout=0.5)
            client.ping()
            return client
        except Exception:
            continue
    return None


_redis = _find_redis()
pytestmark = pytest.mark.skipif(
    _redis is None, reason="no Redis server reachable (see module docstring)"
)


@pytest.fixture
def limiter():
    client = _redis
    # Clean slate for the buckets used below.
    for key in ("auth:ratelimit:lua-key-1:10.9.9.9",):
        client.delete(key)
    yield RedisRateLimiter(redis_client=client)
    for key in ("auth:ratelimit:lua-key-1:10.9.9.9",):
        client.delete(key)


class TestRealLuaScript:
    """Execute the real Lua script end-to-end."""

    def test_allow_path_remaining_counts_down(self, limiter):
        r1 = limiter.is_allowed("lua-key-1", "10.9.9.9", 3)
        r2 = limiter.is_allowed("lua-key-1", "10.9.9.9", 3)
        r3 = limiter.is_allowed("lua-key-1", "10.9.9.9", 3)
        assert r1.allowed and r1.remaining == 2
        assert r2.allowed and r2.remaining == 1
        assert r3.allowed and r3.remaining == 0

    def test_reject_path_returns_retry_after(self, limiter):
        """
        The reject path must not raise a Lua error (previously:
        'attempt to perform arithmetic on ... nil/string value') and must
        produce a sane Retry-After bound by the window.
        """

        for _ in range(3):
            assert limiter.is_allowed("lua-key-1", "10.9.9.9", 3).allowed

        denied = limiter.is_allowed("lua-key-1", "10.9.9.9", 3)
        assert denied.allowed is False
        assert denied.remaining == 0
        assert 0 < denied.retry_after <= limiter.WINDOW

    def test_buckets_are_isolated_per_key(self, limiter):
        for _ in range(3):
            limiter.is_allowed("lua-key-1", "10.9.9.9", 3)

        # Exhausted key is denied, a fresh key is still allowed.
        assert limiter.is_allowed("lua-key-1", "10.9.9.9", 3).allowed is False
        assert limiter.is_allowed("lua-key-2", "10.9.9.9", 3).allowed is True
