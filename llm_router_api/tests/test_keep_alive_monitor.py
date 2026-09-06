"""
Unit tests for ``llm_router_api.core.monitor.keep_alive_monitor``.

Covers duration parsing, Redis key/member helpers, ``record_usage``
scheduling behaviour (valid, invalid and falsy keep-alive values) and
buffer cleanup.  Uses ``fakeredis``; the background thread is never
started.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from unittest import mock  # noqa: E402

import fakeredis  # noqa: E402
import pytest  # noqa: E402

from llm_router_api.core.monitor.keep_alive_monitor import (  # noqa: E402
    KeepAliveMonitor,
)


def _make_monitor(redis_client=None, **kwargs) -> KeepAliveMonitor:
    if redis_client is None:
        redis_client = fakeredis.FakeRedis(decode_responses=True)
    return KeepAliveMonitor(
        redis_client=redis_client,
        keep_alive=mock.Mock(),
        logger=mock.Mock(),
        **kwargs,
    )


class TestParseDurationSeconds:
    @pytest.mark.parametrize(
        "value,expected",
        [
            ("120s", 120),
            ("45m", 2700),
            ("2h", 7200),
            (" 30S ", 30),
            (b"60s", 60),
            ("", None),
            (None, None),
            ("abc", None),
            ("5x", None),
        ],
    )
    def test_parse(self, value, expected):
        monitor = _make_monitor()
        assert monitor._parse_duration_seconds(value) == expected


class TestKeysAndMembers:
    def test_member_round_trip(self):
        monitor = _make_monitor()
        member = monitor._member("model", "host")
        assert member == "model|host"
        assert monitor._split_member(member) == ("model", "host")

    def test_split_member_on_first_pipe_only(self):
        assert KeepAliveMonitor._split_member("m|x|y") == ("m", "x|y")

    def test_provider_hash_key(self):
        monitor = _make_monitor()
        assert (
            monitor._provider_hash_key("model", "host")
            == "keepalive:provider:model:host"
        )

    def test_next_wakeup_zset_key(self):
        monitor = _make_monitor()
        assert monitor._next_wakeup_zset_key() == "keepalive:providers:next_wakeup"

    def test_decode_redis(self):
        assert KeepAliveMonitor._decode_redis(None) is None
        assert KeepAliveMonitor._decode_redis(b"abc") == "abc"
        assert KeepAliveMonitor._decode_redis("str") == "str"
        assert KeepAliveMonitor._decode_redis(123) == "123"


class TestRecordUsage:
    def test_valid_duration_schedules_wakeup(self):
        redis_client = fakeredis.FakeRedis(decode_responses=True)
        monitor = _make_monitor(redis_client)
        monitor.record_usage("m1", "h1", "120s")

        zset = "keepalive:providers:next_wakeup"
        score = redis_client.zscore(zset, "m1|h1")
        assert score is not None
        assert score > int(time.time())

        assert redis_client.hgetall("keepalive:provider:m1:h1") == {
            "model_name": "m1",
            "host": "h1",
            "keep_alive_seconds": "120",
        }
        assert redis_client.smembers("keepalive:model:m1:hosts") == {"h1"}

    @pytest.mark.parametrize("keep_alive", [None, ""])
    def test_falsy_keep_alive_is_noop(self, keep_alive):
        redis_client = fakeredis.FakeRedis(decode_responses=True)
        monitor = _make_monitor(redis_client)
        monitor.record_usage("m", "h", keep_alive)
        # Early return: nothing is written at all.
        assert redis_client.keys() == []

    def test_invalid_duration_not_scheduled(self):
        # Whitespace and garbage are truthy but unparseable: the provider is
        # recorded with zero seconds and explicitly unscheduled (zrem).
        redis_client = fakeredis.FakeRedis(decode_responses=True)
        monitor = _make_monitor(redis_client)
        monitor.record_usage("m2", "h2", "   ")
        monitor.record_usage("m2", "h2", "garbage")

        # No wake-up scheduled...
        assert (
            redis_client.zscore("keepalive:providers:next_wakeup", "m2|h2") is None
        )
        # ...but the provider hash records zero seconds and the host set is kept.
        assert redis_client.hgetall("keepalive:provider:m2:h2") == {
            "model_name": "m2",
            "host": "h2",
            "keep_alive_seconds": "0",
        }
        assert redis_client.smembers("keepalive:model:m2:hosts") == {"h2"}


class TestLifecycle:
    def test_stop_without_start_raises(self):
        monitor = _make_monitor()
        with pytest.raises(RuntimeError):
            monitor.stop()

    def test_start_stop_round_trip(self):
        monitor = _make_monitor(check_interval=0.01)
        monitor.start()
        assert monitor._thread.is_alive()
        monitor.stop()
        assert not monitor._thread.is_alive()

    def test_clear_buffers_removes_provider_keys_and_zset(self):
        redis_client = fakeredis.FakeRedis(decode_responses=True)
        monitor = _make_monitor(redis_client)
        redis_client.hset("keepalive:provider:a:b", "model_name", "a")
        redis_client.hset("keepalive:provider:c:d", "model_name", "c")
        redis_client.zadd("keepalive:providers:next_wakeup", {"a|b": 1, "c|d": 2})

        monitor._clear_buffers()

        assert (
            redis_client.exists("keepalive:provider:a:b", "keepalive:provider:c:d")
            == 0
        )
        assert redis_client.zrange("keepalive:providers:next_wakeup", 0, -1) == []
