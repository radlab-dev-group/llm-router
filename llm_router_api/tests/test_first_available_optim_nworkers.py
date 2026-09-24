"""
Unit tests for ``llm_router_api.core.lb.strategies.first_available_optim_nworkers``.

The strategy is exercised in isolation (no real Redis, no monitor
threads): the instance is created with ``__new__`` and the attributes
used by the selection steps are stubbed.  Redis state is simulated with
``fakeredis``; the worker-slot Lua scripts are mocked with Python
emulators of their exact semantics (``lupa`` is not installed, so
fakeredis cannot execute Lua).
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from unittest import mock  # noqa: E402

import fakeredis  # noqa: E402
import pytest  # noqa: E402

from llm_router_api.core.lb.strategies.first_available_optim_nworkers import (
    FirstAvailableOptimNWorkersStrategy,
)  # noqa: E402
from llm_router_api.core.utils import StrategyHelpers  # noqa: E402


def _acquire_slot_emulator(redis_client):
    """Python twin of ``_ACQUIRE_SLOT_LUA`` running on the fake client."""

    def _run(keys=None, args=None):
        key, field, limit = keys[0], args[0], int(args[1])
        current = int(redis_client.hget(key, field) or 0)
        if current < limit:
            redis_client.hset(key, field, current + 1)
            return current + 1
        return 0

    return _run


def _release_slot_emulator(redis_client):
    """Python twin of ``_RELEASE_SLOT_LUA`` running on the fake client."""

    def _run(keys=None, args=None):
        key, field = keys[0], args[0]
        current = int(redis_client.hget(key, field) or 0)
        if current <= 1:
            redis_client.hdel(key, field)
            return 0
        redis_client.hset(key, field, current - 1)
        return current - 1

    return _run


def _make_strategy(timeout: float = 60) -> FirstAvailableOptimNWorkersStrategy:
    """
    Build an isolated strategy instance (bypassing the constructor) with
    the attributes required by the selection steps and the slot scripts
    emulated on top of fakeredis.
    """
    strategy = FirstAvailableOptimNWorkersStrategy.__new__(
        FirstAvailableOptimNWorkersStrategy
    )
    strategy.redis_client = fakeredis.FakeRedis(decode_responses=True)
    strategy.logger = mock.Mock()
    strategy.timeout = timeout
    strategy.redis_health_check = SimpleNamespace(check_interval=0.02)
    strategy._get_redis_key = lambda model_name: f"model:{model_name}"
    strategy._provider_field = (
        lambda provider: f"{provider.get('id', 'x')}:is_chosen"
    )
    strategy._host_key = lambda host: f"host:{host}"
    strategy._acquire_script = mock.Mock(return_value=1)
    strategy.keep_alive_monitor = mock.Mock()
    strategy.init_provider = mock.Mock(return_value=("model:test", False))
    strategy._get_active_providers = lambda model_name, providers: list(providers)
    strategy._acquire_slot_script = mock.Mock(
        side_effect=_acquire_slot_emulator(strategy.redis_client)
    )
    strategy._release_slot_script = mock.Mock(
        side_effect=_release_slot_emulator(strategy.redis_client)
    )
    return strategy


def _providers() -> list:
    return [
        {"id": "p1", "api_host": "h1", "nworkers": 1},
        {"id": "p2", "api_host": "h2", "nworkers": 2},
        {"id": "p3", "api_host": "h3", "nworkers": 4},
    ]


class TestNworkersParsing:
    """``StrategyHelpers.nworkers`` soft validation of the config field."""

    def test_missing_field_defaults_to_one(self):
        assert StrategyHelpers.nworkers({}) == 1

    def test_int_accepted(self):
        assert StrategyHelpers.nworkers({"nworkers": 4}) == 4

    def test_numeric_string_accepted(self):
        assert StrategyHelpers.nworkers({"nworkers": "4"}) == 4

    @pytest.mark.parametrize("value", [0, -1, "abc", None, 2.5, True])
    def test_invalid_values_fall_back_to_one(self, value):
        assert StrategyHelpers.nworkers({"nworkers": value}) == 1

    def test_custom_default(self):
        assert StrategyHelpers.nworkers({}, default=3) == 3

    def test_none_provider(self):
        assert StrategyHelpers.nworkers(None) == 1
        assert StrategyHelpers.nworkers(None, default=2) == 2


class TestSlotAcquireRelease:
    """Worker-slot counter semantics through the strategy hooks."""

    def test_acquire_up_to_limit(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1", "nworkers": 2}
        assert strategy._try_acquire("m", provider) is not None
        assert strategy._try_acquire("m", provider) is not None
        assert strategy.redis_client.hget("model:m:in_use", "p1") == "2"
        # provider saturated -> third acquisition must fail
        assert strategy._try_acquire("m", provider) is None

    def test_missing_field_counts_as_zero(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1"}
        assert strategy.redis_client.hget("model:m:in_use", "p1") is None
        assert strategy._try_acquire("m", provider) is not None
        assert strategy.redis_client.hget("model:m:in_use", "p1") == "1"

    def test_release_decrements_and_deletes_at_zero(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1", "nworkers": 2}
        strategy._try_acquire("m", provider)
        strategy._try_acquire("m", provider)
        strategy.put_provider("m", provider)
        assert strategy.redis_client.hget("model:m:in_use", "p1") == "1"
        strategy.put_provider("m", provider)
        assert strategy.redis_client.hget("model:m:in_use", "p1") is None

    def test_excess_release_is_safe(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1"}
        # no slot was acquired -> release must be a silent no-op
        strategy.put_provider("m", provider)
        assert strategy.redis_client.hget("model:m:in_use", "p1") is None
        # a second release must not raise either
        strategy.put_provider("m", provider)
        assert strategy.redis_client.hget("model:m:in_use", "p1") is None

    def test_chosen_field_set_on_acquire_popped_on_release(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1"}
        strategy._try_acquire("m", provider)
        assert provider["__chosen_field"] == "p1"
        strategy.put_provider("m", provider)
        assert "__chosen_field" not in provider


class TestStep4LeastLoaded:
    """Ranking and race handling of the load-aware selection step."""

    def test_picks_least_busy_provider(self):
        strategy = _make_strategy()
        strategy.redis_client.hset("model:m:in_use", "p2", "1")
        provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None
        assert provider["id"] == "p1"  # busy 0 beats busy 1

    def test_skips_saturated_providers(self):
        strategy = _make_strategy()
        strategy.redis_client.hset("model:m:in_use", "p1", "1")  # 1/1 full
        strategy.redis_client.hset("model:m:in_use", "p2", "2")  # 2/2 full
        provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None
        assert provider["id"] == "p3"
        assert strategy.redis_client.hget("model:m:in_use", "p3") == "1"

    def test_skips_inactive_providers(self):
        strategy = _make_strategy()
        # p3 has a free slot but the monitor reports it inactive
        strategy._get_active_providers = lambda model_name, providers: providers[:2]
        strategy.redis_client.hset("model:m:in_use", "p1", "1")  # saturated
        provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None
        assert provider["id"] == "p2"
        # p3 must not have been touched at all
        assert strategy.redis_client.hget("model:m:in_use", "p3") is None

    def test_tie_break_by_relative_load(self):
        strategy = _make_strategy()
        # p1 saturated; p2 and p3 both busy=1: p2 ratio 1/2=0.5,
        # p3 ratio 1/4=0.25 -> p3 wins
        strategy.redis_client.hset("model:m:in_use", "p1", "1")
        strategy.redis_client.hset("model:m:in_use", "p2", "1")
        strategy.redis_client.hset("model:m:in_use", "p3", "1")
        provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None
        assert provider["id"] == "p3"

    def test_tie_break_by_config_order(self):
        strategy = _make_strategy()
        providers = [
            {"id": "a", "api_host": "ha", "nworkers": 2},
            {"id": "b", "api_host": "hb", "nworkers": 2},
        ]
        strategy.redis_client.hset("model:m:in_use", "a", "1")
        strategy.redis_client.hset("model:m:in_use", "b", "1")
        provider = strategy._step4_least_loaded("m", providers)
        assert provider is not None
        assert provider["id"] == "a"  # equal key -> earlier config index

    def test_race_loss_moves_to_next_candidate(self):
        strategy = _make_strategy()
        # all busy=0 so ranking is p1, p2, p3; p1 loses the atomic race
        real_acquire = strategy._acquire_slot_script.side_effect

        def _racing_acquire(keys=None, args=None):
            if args[0] == "p1":
                return 0
            return real_acquire(keys=keys, args=args)

        strategy._acquire_slot_script.side_effect = _racing_acquire
        provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None
        assert provider["id"] == "p2"

    def test_host_occupied_by_other_model_is_skipped(self):
        strategy = _make_strategy()
        strategy.redis_client.hset("host:h1", "model", "other-model")
        strategy.redis_client.hset("model:m:in_use", "p2", "1")
        provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None
        # h1 occupied by another model, p2 more loaded -> p3 wins
        assert provider["id"] == "p3"

    def test_no_free_slot_returns_none(self):
        strategy = _make_strategy()
        strategy.redis_client.hset("model:m:in_use", "p1", "1")
        strategy.redis_client.hset("model:m:in_use", "p2", "2")
        strategy.redis_client.hset("model:m:in_use", "p3", "4")
        assert strategy._step4_least_loaded("m", _providers()) is None


class TestGetProviderEndToEnd:
    """Full ``get_provider`` flow with the emulated slot scripts."""

    def test_step1_with_free_slot(self):
        strategy = _make_strategy()
        strategy.redis_client.set("model:m:last_host", "h2")
        provider = strategy.get_provider("m", _providers())
        assert provider is not None
        assert provider["id"] == "p2"
        # slot counter incremented and bookkeeping recorded
        assert strategy.redis_client.hget("model:m:in_use", "p2") == "1"
        assert strategy.redis_client.get("model:m:last_host") == "h2"
        assert strategy.redis_client.sismember("model:m:hosts", "h2")
        strategy.keep_alive_monitor.record_usage.assert_called_once()

    def test_step4_when_fast_path_finds_nothing(self):
        strategy = _make_strategy()
        # Simulate the fast path (last host / known hosts / unused host)
        # coming up empty; only step 4 has a chance to select a provider.
        strategy._step1_last_host = mock.Mock(return_value=None)
        strategy._step2_existing_hosts = mock.Mock(return_value=None)
        strategy._step3_unused_host = mock.Mock(return_value=None)
        strategy.redis_client.hset("model:m:in_use", "p1", "1")  # saturated
        strategy.redis_client.hset("model:m:in_use", "p2", "1")

        provider = strategy.get_provider("m", _providers())
        assert provider is not None
        assert provider["id"] == "p3"  # least loaded with a free slot
        assert strategy.redis_client.hget("model:m:in_use", "p3") == "1"
        strategy.keep_alive_monitor.record_usage.assert_called_once()

    def test_timeout_when_every_provider_saturated(self):
        strategy = _make_strategy(timeout=0.3)
        providers = _providers()
        # every host known and every provider saturated -> steps 1-4
        # fail and the first-available fallback must wait until timeout
        strategy.redis_client.sadd("model:m:hosts", "h1", "h2", "h3")
        strategy.redis_client.hset("model:m:in_use", "p1", "1")
        strategy.redis_client.hset("model:m:in_use", "p2", "2")
        strategy.redis_client.hset("model:m:in_use", "p3", "4")
        with pytest.raises(TimeoutError, match="m"):
            strategy.get_provider("m", providers)


class TestNworkersOneBehaviour:
    """With ``nworkers`` = 1 the strategy degrades to a binary lock."""

    def test_single_slot_is_binary_lock(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1"}  # default nworkers=1
        assert strategy._try_acquire("m", provider) is not None
        # one slot -> second acquisition must fail, exactly like the lock
        assert strategy._try_acquire("m", provider) is None
        strategy.put_provider("m", provider)
        # slot released -> provider free again
        assert strategy._try_acquire("m", provider) is not None

    def test_step4_with_unit_limits(self):
        strategy = _make_strategy()
        providers = [
            {"id": "p1", "api_host": "h1"},
            {"id": "p2", "api_host": "h2"},
        ]
        strategy.redis_client.hset("model:m:in_use", "p1", "1")
        provider = strategy._step4_least_loaded("m", providers)
        assert provider is not None
        assert provider["id"] == "p2"


class TestClearBuffer:
    def test_removes_in_use_and_optimisation_keys(self):
        strategy = _make_strategy()
        strategy.redis_client.hset("model:m:in_use", "p1", "1")
        strategy.redis_client.set("model:m:last_host", "h1")
        strategy._clear_buffer()
        assert strategy.redis_client.hget("model:m:in_use", "p1") is None
        assert strategy.redis_client.get("model:m:last_host") is None
