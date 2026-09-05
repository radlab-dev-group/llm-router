"""
Unit tests for ``llm_router_api.core.lb.strategies.first_available_optim``.

The strategy is exercised in isolation (no real Redis, no monitor threads):
the instance is created with ``__new__`` and the attributes used by the
selection steps are stubbed.  Redis state is simulated with ``fakeredis``.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from unittest import mock  # noqa: E402

import fakeredis  # noqa: E402
import pytest  # noqa: E402

from llm_router_api.core.lb.strategies.first_available_optim import (
    FirstAvailableOptimStrategy,
)  # noqa: E402


def _make_strategy(acquire_result: int = 1) -> FirstAvailableOptimStrategy:
    """
    Build an isolated strategy instance (bypassing the constructor) with the
    attributes required by the selection steps.
    """
    strategy = FirstAvailableOptimStrategy.__new__(FirstAvailableOptimStrategy)
    strategy.redis_client = fakeredis.FakeRedis(decode_responses=True)
    strategy.logger = mock.Mock()
    strategy._get_redis_key = lambda model_name: f"model:{model_name}"
    strategy._provider_field = (
        lambda provider: f"{provider.get('id', 'x')}:is_chosen"
    )
    strategy._host_key = lambda host: f"host:{host}"
    strategy._acquire_script = mock.Mock(return_value=acquire_result)
    strategy.keep_alive_monitor = mock.Mock()
    strategy.init_provider = mock.Mock(return_value=("model:test", False))
    strategy._get_active_providers = lambda model_name, providers: list(providers)
    strategy.put_provider = mock.Mock()
    return strategy


def _providers() -> list:
    return [
        {"id": "p1", "api_host": "h1"},
        {"id": "p2", "api_host": "h2"},
    ]


class TestIsHostFree:
    def test_free_host(self):
        strategy = _make_strategy()
        assert strategy._is_host_free("h1", "model") is True

    def test_same_model_occupying_is_free(self):
        strategy = _make_strategy()
        strategy.redis_client.hset("host:h1", "model", "model")
        assert strategy._is_host_free("h1", "model") is True

    def test_same_model_with_prefix_occupying_is_free(self):
        strategy = _make_strategy()
        strategy.redis_client.hset("host:h1", "model", "model:model")
        assert strategy._is_host_free("h1", "model") is True

    def test_other_model_occupying_is_busy(self):
        strategy = _make_strategy()
        strategy.redis_client.hset("host:h1", "model", "other")
        assert strategy._is_host_free("h1", "model") is False


class TestStep1LastHost:
    def test_reuses_last_host_when_free(self):
        strategy = _make_strategy()
        strategy.redis_client.set("model:m:last_host", "h2")
        provider = strategy._step1_last_host("m", _providers())
        assert provider is not None
        assert provider["api_host"] == "h2"
        assert provider["__chosen_field"] == "p2:is_chosen"

    def test_no_last_host_recorded(self):
        strategy = _make_strategy()
        assert strategy._step1_last_host("m", _providers()) is None

    def test_last_host_not_in_providers(self):
        strategy = _make_strategy()
        strategy.redis_client.set("model:m:last_host", "hX")
        assert strategy._step1_last_host("m", _providers()) is None

    def test_last_host_occupied_by_other_model(self):
        strategy = _make_strategy()
        strategy.redis_client.set("model:m:last_host", "h1")
        strategy.redis_client.hset("host:h1", "model", "other")
        assert strategy._step1_last_host("m", _providers()) is None


class TestStep2ExistingHosts:
    def test_empty_known_hosts_set(self):
        strategy = _make_strategy()
        assert strategy._step2_existing_hosts("m", _providers()) is None

    def test_selects_provider_on_known_host(self):
        strategy = _make_strategy()
        strategy.redis_client.sadd("model:m:hosts", "h2")
        provider = strategy._step2_existing_hosts("m", _providers())
        assert provider is not None
        assert provider["api_host"] == "h2"


class TestStep3UnusedHost:
    def test_picks_host_outside_known_set(self):
        strategy = _make_strategy()
        strategy.redis_client.sadd("model:m:hosts", "h2")
        provider = strategy._step3_unused_host("m", _providers())
        assert provider is not None
        assert provider["api_host"] == "h1"

    def test_all_hosts_known_returns_none(self):
        strategy = _make_strategy()
        strategy.redis_client.sadd("model:m:hosts", "h1", "h2")
        assert strategy._step3_unused_host("m", _providers()) is None


class TestSelectProvider:
    def test_skips_provider_without_host(self):
        strategy = _make_strategy()
        providers = [{"id": "p0"}, {"id": "p1", "api_host": "h1"}]
        provider = strategy._select_provider(
            "m", providers, host_predicate=lambda host: True
        )
        assert provider is not None
        assert provider["id"] == "p1"

    def test_negative_predicate_skips_provider(self):
        strategy = _make_strategy()
        provider = strategy._select_provider(
            "m", _providers(), host_predicate=lambda host: host == "h1"
        )
        assert provider is not None
        assert provider["api_host"] == "h1"

    def test_busy_host_skipped(self):
        strategy = _make_strategy()
        strategy.redis_client.hset("host:h1", "model", "other")
        provider = strategy._select_provider(
            "m", _providers(), host_predicate=lambda host: True
        )
        # h1 is busy → only h2 can be acquired.
        assert provider is not None
        assert provider["api_host"] == "h2"

    def test_acquisition_failure_returns_none(self):
        strategy = _make_strategy(acquire_result=0)
        provider = strategy._select_provider(
            "m", _providers(), host_predicate=lambda host: True
        )
        assert provider is None


class TestRecordSelection:
    def test_bookkeeping_written(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h9", "keep_alive": "120s"}
        strategy._record_selection("m", provider)
        assert strategy.redis_client.get("model:m:last_host") == "h9"
        assert strategy.redis_client.sismember("model:m:hosts", "h9")
        assert strategy.redis_client.hget("host:h9", "model") == "m"
        strategy.keep_alive_monitor.record_usage.assert_called_once_with(
            model_name="m", host="h9", keep_alive="120s"
        )

    def test_provider_without_host_is_noop(self):
        strategy = _make_strategy()
        strategy._record_selection("m", {"id": "p"})
        assert strategy.redis_client.get("model:m:last_host") is None
        strategy.keep_alive_monitor.record_usage.assert_not_called()


class TestGetProvider:
    def test_empty_providers_returns_none(self):
        strategy = _make_strategy()
        assert strategy.get_provider("m", []) is None

    def test_success_on_step1_records_selection(self):
        strategy = _make_strategy()
        strategy.redis_client.set("model:m:last_host", "h2")
        provider = strategy.get_provider("m", _providers())
        assert provider is not None
        assert provider["api_host"] == "h2"
        assert strategy.redis_client.get("model:m:last_host") == "h2"
        assert strategy.redis_client.sismember("model:m:hosts", "h2")
        strategy.keep_alive_monitor.record_usage.assert_called_once()

    def test_success_on_step3_when_no_state(self):
        strategy = _make_strategy()
        provider = strategy.get_provider("m", _providers())
        assert provider is not None
        assert provider["api_host"] == "h1"
