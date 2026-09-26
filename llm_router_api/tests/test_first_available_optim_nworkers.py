"""
Unit tests for ``llm_router_api.core.lb.strategies.first_available_optim_nworkers``.

The strategy is exercised against ``fakeredis`` with **real** Redis state and
the **real** worker-slot Lua scripts (``lupa`` makes ``fakeredis`` execute
them), but with no monitor threads and no model configuration file: the
instance is built with ``__new__`` and only the collaborators that would need
a live router are stubbed.

Deliberately *not* stubbed: ``_get_redis_key``, ``_provider_key``,
``_provider_field``, ``_host_key``, ``_is_host_free``, ``_select_provider`` and
``_record_selection``.  An earlier version of this file overrode them and, as a
result, shipped three bugs that the suite could not have caught: the strategy
prefix was never applied to the keys, the ``:in_use`` keys of every model were
deleted on start-up, and the "config order" tie-break used the order of a Redis
set.

To keep that from happening again, :meth:`_make_strategy` returns the active
providers in an order that differs from the configuration order, mimicking
``SMEMBERS``.
"""

from __future__ import annotations

import os
import time
import threading
from types import SimpleNamespace

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from unittest import mock  # noqa: E402

import fakeredis  # noqa: E402
import pytest  # noqa: E402

from llm_router_api.core.lb.strategies import (
    first_available_optim_nworkers as _mod,
)  # noqa: E402
from llm_router_api.core.lb.strategies.first_available_optim_nworkers import (  # noqa: E402
    LEASE_FIELD,
    FirstAvailableOptimNWorkersStrategy,
)
from llm_router_api.core.utils import StrategyHelpers  # noqa: E402

PREFIX = "fa_optim_nworkers_"


def _make_strategy(
    timeout: float = 60,
    slot_lease_seconds: int = 120,
    active_order=None,
):
    """
    Build an isolated strategy instance (bypassing the constructor).

    Only the collaborators that require a running router are stubbed; every
    key-deriving and selection helper of the class is the real one.

    Parameters
    ----------
    active_order: list, optional
        Provider ids in the order the health monitor reports them.  Defaults
        to the reverse of the configuration order, which is what a Redis
        ``SMEMBERS`` round trip can legitimately return and what a naive
        "config order" tie-break mistakes for it.
    """
    strategy = FirstAvailableOptimNWorkersStrategy.__new__(
        FirstAvailableOptimNWorkersStrategy
    )
    strategy.redis_client = fakeredis.FakeRedis(decode_responses=True)
    strategy.logger = mock.Mock()
    strategy.timeout = timeout
    strategy.slot_lease_seconds = slot_lease_seconds
    strategy.strategy_prefix = PREFIX
    strategy.redis_health_check = SimpleNamespace(check_interval=0.02)
    strategy.keep_alive_monitor = mock.Mock()
    strategy._held_leases = {}
    strategy._leases_lock = threading.Lock()
    strategy._next_renew_at = 0.0
    strategy.init_provider = mock.Mock(return_value=(f"{PREFIX}model:test", False))

    order = list(active_order) if active_order is not None else None

    def _active(model_name, providers):
        if order is None:
            return list(reversed(providers))
        by_id = {p["id"]: p for p in providers}
        return [by_id[i] for i in order if i in by_id]

    strategy._get_active_providers = _active

    strategy._acquire_slot_script = strategy.redis_client.register_script(
        _mod._ACQUIRE_SLOT_LUA
    )
    strategy._release_slot_script = strategy.redis_client.register_script(
        _mod._RELEASE_SLOT_LUA
    )
    return strategy


def _use_client(strategy, client):
    """Point an existing strategy instance at another (shared) Redis client."""
    strategy.redis_client = client
    strategy._acquire_slot_script = client.register_script(_mod._ACQUIRE_SLOT_LUA)
    strategy._release_slot_script = client.register_script(_mod._RELEASE_SLOT_LUA)
    return strategy


def _providers() -> list:
    return [
        {"id": "p1", "api_host": "h1", "nworkers": 1},
        {"id": "p2", "api_host": "h2", "nworkers": 2},
        {"id": "p3", "api_host": "h3", "nworkers": 4},
    ]


def _hold(strategy, provider, model_name="m"):
    """Acquire one slot of *provider* and return the acquired dictionary."""
    acquired = strategy._try_acquire(model_name, provider)
    assert acquired is not None, f"could not acquire {provider['id']}"
    return acquired


def _leases(strategy, provider, model_name="m"):
    return strategy.redis_client.zrange(
        strategy._in_use_key(model_name, provider), 0, -1
    )


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


class TestKeyNamespacing:
    """Every model key of this strategy lives under ``strategy_prefix``."""

    def test_model_keys_carry_the_prefix(self):
        strategy = _make_strategy()
        assert strategy._get_redis_key("m") == f"{PREFIX}model:m"
        provider = {"id": "p1", "api_host": "h1"}
        assert strategy._in_use_key("m", provider) == f"{PREFIX}model:m:in_use:p1"

    def test_host_occupancy_stays_shared(self):
        # Which model occupies a physical host is not strategy-local state.
        strategy = _make_strategy()
        assert strategy._host_key("h1") == "host:h1"

    def test_two_providers_of_one_model_do_not_share_a_lease_set(self):
        strategy = _make_strategy()
        p1, p2 = _providers()[0], _providers()[1]
        assert strategy._in_use_key("m", p1) != strategy._in_use_key("m", p2)


class TestSlotAcquireRelease:
    """Worker-slot lease semantics through the strategy hooks."""

    def test_acquire_up_to_limit(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1", "nworkers": 2}
        _hold(strategy, provider)
        _hold(strategy, provider)
        assert len(_leases(strategy, provider)) == 2
        assert strategy._try_acquire("m", provider) is None

    def test_each_request_holds_its_own_lease(self):
        # The whole point of a lease over a counter: two concurrent holders of
        # the same provider are distinguishable, and releasing one leaves the
        # other intact.
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1", "nworkers": 2}
        first = _hold(strategy, provider)
        second = _hold(strategy, provider)
        assert first[LEASE_FIELD] != second[LEASE_FIELD]

        strategy.put_provider("m", first)
        assert _leases(strategy, provider) == [second[LEASE_FIELD]]

    def test_release_frees_one_slot(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1", "nworkers": 2}
        acquired = [_hold(strategy, provider) for _ in range(2)]
        assert strategy._try_acquire("m", provider) is None
        strategy.put_provider("m", acquired[0])
        assert strategy._try_acquire("m", provider) is not None

    def test_release_without_a_token_is_a_noop(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1"}
        held = _hold(strategy, provider)
        # A release carrying no token must not touch somebody else's slot.
        strategy.put_provider("m", dict(provider))
        assert _leases(strategy, provider) == [held[LEASE_FIELD]]

    def test_double_release_is_safe(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1"}
        acquired = _hold(strategy, provider)
        strategy.put_provider("m", acquired)
        assert _leases(strategy, provider) == []
        strategy.put_provider("m", acquired)

    def test_acquire_does_not_mutate_the_provider_dictionary(self):
        # ``providers`` is the shared model configuration: writing the token
        # into it would let one request release another request's slot, and
        # nworkers > 1 makes that race reachable.
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1", "nworkers": 2}
        acquired = _hold(strategy, provider)
        assert LEASE_FIELD not in provider
        assert acquired is not provider
        strategy.put_provider("m", acquired)
        assert LEASE_FIELD not in provider

    def test_lease_expires_and_capacity_comes_back(self):
        strategy = _make_strategy(slot_lease_seconds=1)
        provider = {"id": "p1", "api_host": "h1", "nworkers": 1}
        _hold(strategy, provider)
        assert strategy._try_acquire("m", provider) is None
        # The holder never releases (crashed process); the lease lapses.
        time.sleep(1.1)
        assert strategy._try_acquire("m", provider) is not None

    def test_busy_count_ignores_expired_leases(self):
        strategy = _make_strategy(slot_lease_seconds=1)
        provider = {"id": "p1", "api_host": "h1", "nworkers": 2}
        _hold(strategy, provider)
        assert strategy._busy_count("m", provider) == 1
        time.sleep(1.1)
        assert strategy._busy_count("m", provider) == 0


class TestLeaseRenewal:
    """A live process keeps its slots alive while the monitor ticks."""

    def test_renew_pushes_the_expiry_into_the_future(self):
        strategy = _make_strategy(slot_lease_seconds=1)
        provider = {"id": "p1", "api_host": "h1", "nworkers": 1}
        acquired = _hold(strategy, provider)
        token = acquired[LEASE_FIELD]
        key = strategy._in_use_key("m", provider)

        strategy._renew_held_leases()
        score = strategy.redis_client.zscore(key, token)
        assert score > time.time() * 1000

    def test_renew_touches_only_this_process_leases(self):
        strategy = _make_strategy(slot_lease_seconds=60)
        provider = {"id": "p1", "api_host": "h1", "nworkers": 2}
        strategy._renew_held_leases()  # nothing held yet -> must not raise
        acquired = _hold(strategy, provider)
        foreign = "some-other-process"
        stale = int(time.time() * 1000) - 10_000
        key = strategy._in_use_key("m", provider)
        strategy.redis_client.zadd(key, {foreign: stale})

        strategy._renew_held_leases()
        assert strategy.redis_client.zscore(key, acquired[LEASE_FIELD]) > stale
        assert strategy.redis_client.zscore(key, foreign) == stale

    def test_renew_swallows_redis_failures(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1"}
        _hold(strategy, provider)
        with mock.patch.object(
            strategy.redis_client, "pipeline", side_effect=ConnectionError("down")
        ):
            strategy._renew_held_leases()  # must not raise
        assert strategy.logger.warning.called

    def test_renewal_is_throttled_below_the_lease_lifetime(self):
        # The monitor ticks once a second; a 120s lease must not be rewritten
        # once a second.
        strategy = _make_strategy(slot_lease_seconds=120)
        provider = {"id": "p1", "api_host": "h1"}
        _hold(strategy, provider)

        strategy._renew_held_leases()
        writes_after_first = strategy.redis_client.zscore(
            strategy._in_use_key("m", provider),
            next(iter(strategy._held_leases)),
        )
        strategy.redis_client.zadd(
            strategy._in_use_key("m", provider),
            {next(iter(strategy._held_leases)): 1},
        )
        strategy._renew_held_leases()  # inside the throttle window -> no-op
        assert (
            strategy.redis_client.zscore(
                strategy._in_use_key("m", provider),
                next(iter(strategy._held_leases)),
            )
            == 1
        )
        assert writes_after_first is not None

    def test_renewal_runs_again_once_the_window_passes(self):
        strategy = _make_strategy(slot_lease_seconds=120)
        provider = {"id": "p1", "api_host": "h1"}
        _hold(strategy, provider)
        strategy._renew_held_leases()
        strategy._next_renew_at = 0.0  # window elapsed
        token = next(iter(strategy._held_leases))
        strategy.redis_client.zadd(strategy._in_use_key("m", provider), {token: 1})

        strategy._renew_held_leases()
        assert (
            strategy.redis_client.zscore(strategy._in_use_key("m", provider), token)
            > 1
        )


class TestStepLeastLoaded:
    """Ranking and race handling of the load-aware selection step."""

    def test_picks_least_busy_provider(self):
        strategy = _make_strategy(active_order=["p1", "p2", "p3"])
        _hold(strategy, {"id": "p2", "api_host": "h2", "nworkers": 2})
        provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None
        assert provider["id"] == "p1"  # busy 0 beats busy 1

    def test_skips_saturated_providers(self):
        strategy = _make_strategy(active_order=["p1", "p2", "p3"])
        _hold(strategy, {"id": "p1", "api_host": "h1", "nworkers": 1})
        _hold(strategy, {"id": "p2", "api_host": "h2", "nworkers": 2})
        _hold(strategy, {"id": "p2", "api_host": "h2", "nworkers": 2})
        provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None
        assert provider["id"] == "p3"

    def test_skips_inactive_providers(self):
        strategy = _make_strategy(active_order=["p1", "p2"])
        # p3 has a free slot but the monitor reports it inactive
        _hold(strategy, {"id": "p1", "api_host": "h1", "nworkers": 1})
        provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None
        assert provider["id"] == "p2"
        assert (
            strategy.redis_client.zcard(strategy._in_use_key("m", {"id": "p3"})) == 0
        )

    def test_tie_break_by_relative_load(self):
        strategy = _make_strategy(active_order=["p1", "p2", "p3"])
        # p1 saturated; p2 and p3 both busy=1: p2 ratio 1/2=0.5,
        # p3 ratio 1/4=0.25 -> p3 wins
        _hold(strategy, {"id": "p1", "api_host": "h1", "nworkers": 1})
        _hold(strategy, {"id": "p2", "api_host": "h2", "nworkers": 2})
        _hold(strategy, {"id": "p3", "api_host": "h3", "nworkers": 4})
        provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None
        assert provider["id"] == "p3"

    def test_tie_break_uses_configuration_not_monitor_order(self):
        # ``_get_active_providers`` reports b before a; the tie must still be
        # broken by the order of the ``providers`` argument.
        strategy = _make_strategy(active_order=["b", "a"])
        providers = [
            {"id": "a", "api_host": "ha", "nworkers": 2},
            {"id": "b", "api_host": "hb", "nworkers": 2},
        ]
        provider = strategy._step4_least_loaded("m", providers)
        assert provider is not None
        assert provider["id"] == "a"

    def test_race_loss_moves_to_next_candidate(self):
        strategy = _make_strategy(active_order=["p1", "p2", "p3"])
        real_script = strategy._acquire_slot_script

        def _racing(keys=None, args=None):
            # p1 always loses the atomic race
            if strategy._in_use_key("m", {"id": "p1"}) in (keys or []):
                return 0
            return real_script(keys=keys, args=args)

        strategy._acquire_slot_script = _racing
        provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None
        assert provider["id"] == "p2"

    def test_host_occupied_by_other_model_is_skipped(self):
        strategy = _make_strategy(active_order=["p1", "p2", "p3"])
        strategy.redis_client.hset("host:h1", "model", "other-model")
        _hold(strategy, {"id": "p2", "api_host": "h2", "nworkers": 2})
        provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None
        # h1 occupied by another model, p2 more loaded -> p3 wins
        assert provider["id"] == "p3"

    def test_no_free_slot_returns_none(self):
        strategy = _make_strategy(active_order=["p1", "p2", "p3"])
        for pid, limit in (("p1", 1), ("p2", 2), ("p3", 4)):
            for _ in range(limit):
                _hold(
                    strategy,
                    {"id": pid, "api_host": f"h{pid[-1]}", "nworkers": limit},
                )
        assert strategy._step4_least_loaded("m", _providers()) is None

    def test_no_active_providers_returns_none(self):
        strategy = _make_strategy(active_order=[])
        assert strategy._step4_least_loaded("m", _providers()) is None


class TestStepOrdering:
    """
    The load-aware step must decide *before* the host-reuse steps.

    Steps “reuse any known host“ and “pick an unused host“ partition the
    provider list on “host already known“ / “host not known yet“, so together
    they consider every provider that has a free slot and always answer with
    the first one in configuration order.  With the load-aware step behind
    them it could never decide anything.
    """

    def test_least_loaded_step_runs_before_the_host_reuse_steps(self):
        strategy = _make_strategy()
        steps = strategy._optimization_steps()
        bound = [s.__name__ for s in steps]
        assert bound == [
            "_step1_last_host",
            "_step4_least_loaded",
            "_step2_existing_hosts",
            "_step3_unused_host",
        ]

    def test_saturated_hot_host_spreads_by_load_not_config_order(self):
        # Regression: p1 is the last host and saturated, p2 is at 1/2 and p3
        # is idle.  Configuration order would answer p2, least load is p3.
        strategy = _make_strategy(active_order=["p1", "p2", "p3"])
        strategy.redis_client.set(f"{PREFIX}model:m:last_host", "h1")
        _hold(strategy, {"id": "p1", "api_host": "h1", "nworkers": 1})
        _hold(strategy, {"id": "p2", "api_host": "h2", "nworkers": 2})
        strategy.redis_client.sadd(f"{PREFIX}model:m:hosts", "h1", "h2", "h3")

        provider = strategy.get_provider("m", _providers())
        assert provider is not None
        assert provider["id"] == "p3"

    def test_cold_start_spreads_by_load_not_config_order(self):
        # No last host, no known hosts: p1 is already at 1/2 while p2 and p3
        # are idle -> an idle one wins instead of the first configured one.
        strategy = _make_strategy(active_order=["p1", "p2", "p3"])
        _hold(strategy, {"id": "p1", "api_host": "h1", "nworkers": 2})
        provider = strategy.get_provider("m", _providers())
        assert provider is not None
        assert provider["id"] in {"p2", "p3"}

    def test_free_last_host_still_wins(self):
        # Cache affinity is kept while the warm host has capacity: p1 is the
        # last host at 1/3 while the idle p3 would win a pure load ranking.
        strategy = _make_strategy(active_order=["p1", "p2", "p3"])
        providers = [
            {"id": "p1", "api_host": "h1", "nworkers": 3},
            {"id": "p2", "api_host": "h2", "nworkers": 4},
            {"id": "p3", "api_host": "h3", "nworkers": 4},
        ]
        strategy.redis_client.set(f"{PREFIX}model:m:last_host", "h1")
        _hold(strategy, providers[0])
        provider = strategy.get_provider("m", providers)
        assert provider is not None
        assert provider["id"] == "p1"


class TestGetProviderEndToEnd:
    """Full ``get_provider`` flow against the real Redis state."""

    def test_step1_with_free_slot(self):
        strategy = _make_strategy(active_order=["p1", "p2", "p3"])
        strategy.redis_client.set(f"{PREFIX}model:m:last_host", "h2")
        provider = strategy.get_provider("m", _providers())
        assert provider is not None
        assert provider["id"] == "p2"
        assert len(_leases(strategy, {"id": "p2"})) == 1
        assert strategy.redis_client.get(f"{PREFIX}model:m:last_host") == "h2"
        assert strategy.redis_client.sismember(f"{PREFIX}model:m:hosts", "h2")
        strategy.keep_alive_monitor.record_usage.assert_called_once()

    def test_bookkeeping_written_under_the_prefix(self):
        strategy = _make_strategy(active_order=["p1", "p2", "p3"])
        provider = strategy.get_provider("m", _providers())
        host = StrategyHelpers.host_from_provider(provider)
        assert strategy.redis_client.get(f"{PREFIX}model:m:last_host") == host
        assert strategy.redis_client.sismember(f"{PREFIX}model:m:hosts", host)
        assert strategy.redis_client.hget(f"host:{host}", "model")

    def test_timeout_when_every_provider_saturated(self):
        strategy = _make_strategy(timeout=0.3, active_order=["p1", "p2", "p3"])
        providers = _providers()
        strategy.redis_client.sadd(f"{PREFIX}model:m:hosts", "h1", "h2", "h3")
        for pid, limit in (("p1", 1), ("p2", 2), ("p3", 4)):
            for _ in range(limit):
                _hold(strategy, {"id": pid, "api_host": "h?", "nworkers": limit})
        with pytest.raises(TimeoutError, match="m"):
            strategy.get_provider("m", providers)

    def test_released_slot_unblocks_a_waiting_caller(self):
        strategy = _make_strategy(timeout=5, active_order=["p1"])
        provider = _hold(strategy, {"id": "p1", "api_host": "h1", "nworkers": 1})
        threading_holder = _release_after(
            0.1, lambda: strategy.put_provider("m", provider)
        )
        acquired = strategy.get_provider(
            "m", [{"id": "p1", "api_host": "h1", "nworkers": 1}]
        )
        assert acquired is not None
        threading_holder.join(timeout=5)


class TestReleaseViaApiModel:
    """
    Release along the real call path.

    ``EndpointBase.unset_model`` hands the strategy
    ``api_model_provider.as_dict()`` rather than the dictionary returned by
    ``get_provider``, so the lease token has to travel through
    :class:`~llm_router_api.core.model_handler.ApiModel`.
    """

    def test_slot_is_released_from_an_as_dict_payload(self):
        from llm_router_api.core.model_handler import ApiModel

        strategy = _make_strategy()
        cfg = {
            "id": "p1",
            "api_host": "h1",
            "api_type": "vllm",
            "input_size": 100,
            "nworkers": 1,
        }
        acquired = strategy.get_provider("m", [dict(cfg)])
        assert acquired is not None

        api_model = ApiModel.from_config("m", acquired)
        assert strategy._try_acquire("m", dict(cfg)) is None

        strategy.put_provider("m", api_model.as_dict())

        assert strategy._try_acquire("m", dict(cfg)) is not None

    def test_releasing_a_foreign_provider_does_not_free_the_holder(self):
        from llm_router_api.core.model_handler import ApiModel

        strategy = _make_strategy()
        cfg = {
            "id": "p1",
            "api_host": "h1",
            "api_type": "vllm",
            "input_size": 100,
            "nworkers": 1,
        }
        acquired = _hold(strategy, dict(cfg))
        # A stale payload without a token (e.g. a fake provider) must not
        # release the slot somebody else holds.
        foreign = ApiModel.from_config("m", {**cfg, "id": "p9", "api_host": "h9"})
        strategy.put_provider("m", foreign.as_dict())
        assert strategy._try_acquire("m", dict(cfg)) is None
        assert acquired[LEASE_FIELD]


class TestNworkersOneBehaviour:
    """With ``nworkers`` = 1 a provider admits exactly one request."""

    def test_single_slot_admits_one_request(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1"}  # default nworkers=1
        acquired = _hold(strategy, provider)
        assert strategy._try_acquire("m", provider) is None
        strategy.put_provider("m", acquired)
        assert strategy._try_acquire("m", provider) is not None


class TestBufferCleanup:
    """Start-up cleanup must not destroy another process' live state."""

    def test_in_use_leases_survive_clear_buffer(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1"}
        held = _hold(strategy, provider)
        strategy._clear_buffer()
        assert _leases(strategy, provider) == [held[LEASE_FIELD]]

    def test_second_instance_start_does_not_free_another_s_slots(self):
        first = _make_strategy()
        provider = {"id": "p1", "api_host": "h1", "nworkers": 1}
        _hold(first, provider)
        assert first._try_acquire("m", provider) is None

        # A second router worker process starts up and clears its buffers.
        second = _make_strategy()
        _use_client(second, first.redis_client)
        second._clear_buffer()

        assert first._try_acquire("m", provider) is None

    def test_clear_buffer_removes_own_optimisation_keys_only(self):
        strategy = _make_strategy()
        strategy.redis_client.set(f"{PREFIX}model:m:last_host", "h1")
        strategy.redis_client.sadd(f"{PREFIX}model:m:hosts", "h1")
        # keys belonging to another strategy sharing the Redis database
        strategy.redis_client.set("model:m:last_host", "other")
        strategy.redis_client.set("fa_optim_model:m:last_host", "other")

        strategy._clear_buffer()

        assert strategy.redis_client.get(f"{PREFIX}model:m:last_host") is None
        assert not strategy.redis_client.smembers(f"{PREFIX}model:m:hosts")
        assert strategy.redis_client.get("model:m:last_host") == "other"
        assert strategy.redis_client.get("fa_optim_model:m:last_host") == "other"


class TestErrorHandling:
    """A Redis problem degrades selection; it never surfaces as a crash."""

    def test_acquire_failure_is_logged_and_skipped(self):
        strategy = _make_strategy()
        provider = {"id": "p1", "api_host": "h1"}
        strategy._acquire_slot_script = mock.Mock(
            side_effect=ConnectionError("down")
        )
        assert strategy._try_acquire("m", provider) is None
        assert strategy.logger.warning.called

    def test_busy_count_failure_degrades_to_zero(self):
        strategy = _make_strategy(active_order=["p1", "p2"])
        _hold(strategy, {"id": "p1", "api_host": "h1", "nworkers": 1})
        with mock.patch.object(
            strategy.redis_client, "pipeline", side_effect=ConnectionError("down")
        ):
            assert strategy._busy_count("m", {"id": "p1", "api_host": "h1"}) == 0
        assert strategy.logger.warning.called

    def test_step4_survives_a_redis_failure(self):
        strategy = _make_strategy(active_order=["p1", "p2"])
        with mock.patch.object(
            strategy.redis_client, "pipeline", side_effect=ConnectionError("down")
        ):
            # Must not raise; selection falls through to the atomic acquire.
            provider = strategy._step4_least_loaded("m", _providers())
        assert provider is not None


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _release_after(delay, release):
    """Run *release* on a background thread after *delay* seconds."""
    worker = threading.Thread(target=lambda: (time.sleep(delay), release()))
    worker.start()
    return worker
