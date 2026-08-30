"""
M5 — ``balanced`` / ``weighted`` must be **globally** consistent across
multiple workers (processes) sharing one Redis, not per‑process.

The acceptance scenario: two strategy instances ("workers") share a single
Redis.  Routing N requests across the two workers must produce a *global*
distribution that matches the configured weights (within a statistical
tolerance), even though no single worker sees all of the traffic itself.
"""

import math
from typing import Any, Dict, List

import pytest

from llm_router_api.core.lb.lb_counters import LbCounters
from llm_router_api.core.lb.strategies.balanced import LoadBalancedStrategy
from llm_router_api.core.lb.strategies.weighted import (
    DynamicWeightedStrategy,
    WeightedStrategy,
)


# ---------------------------------------------------------------------------
# Minimal FakeRedis supporting the commands LbCounters uses
# ---------------------------------------------------------------------------
class FakeRedis:
    def __init__(self) -> None:
        self._hash: Dict[str, Dict[str, int]] = {}
        self._incr: Dict[str, int] = {}
        self._expired: set = set()
        self._fail = False

    def hgetall(self, key: str) -> Dict[str, str]:
        if self._fail:
            raise RuntimeError("redis down")
        if key in self._expired:
            return {}
        return {k: str(v) for k, v in self._hash.get(key, {}).items()}

    def hincrby(self, key: str, field: str, amount: int = 1) -> int:
        if self._fail:
            raise RuntimeError("redis down")
        h = self._hash.setdefault(key, {})
        h[field] = h.get(field, 0) + amount
        return h[field]

    def incr(self, key: str) -> int:
        if self._fail:
            raise RuntimeError("redis down")
        v = self._incr.get(key, 0) + 1
        self._incr[key] = v
        return v

    def expire(self, key: str, seconds: int) -> bool:
        return True


class _Config:
    """Trivial stand‑in for models_config_path (strategies only need the key)."""

    pass


def _providers(weights: List[float], names: List[str]) -> List[Dict[str, Any]]:
    out = []
    for name, w in zip(names, weights):
        out.append(
            {
                "id": name,
                "api_host": f"http://{name}:8080",
                "api_type": "vllm",
                "weight": w,
                "name": name,
            }
        )
    return out


def _mk_path():
    # The strategy interface instantiates ApiModelConfig(models_config_path);
    # point at the repo's default so construction succeeds without a real file.
    from pathlib import Path

    return str(
        Path(__file__).resolve().parents[2]
        / "resources"
        / "configs"
        / "models-config.json"
    )


def _distribution(counts: Dict[str, int], total: int) -> Dict[str, float]:
    return {k: v / total for k, v in counts.items()}


def _close_enough(obs: Dict[str, float], exp: Dict[str, float], tol: float) -> bool:
    return all(abs(obs.get(k, 0.0) - exp.get(k, 0.0)) <= tol for k in exp)


# ---------------------------------------------------------------------------
# Weighted strategy: two workers, shared Redis → global weight match
# ---------------------------------------------------------------------------
class TestWeightedGlobal:
    def test_two_workers_shared_redis_match_weights(self):
        shared = FakeRedis()
        names = ["p-a", "p-b", "p-c"]
        weights = [0.6, 0.3, 0.1]
        providers = _providers(weights, names)

        worker1 = WeightedStrategy(
            models_config_path=_mk_path(), redis_client=shared
        )
        worker2 = WeightedStrategy(
            models_config_path=_mk_path(), redis_client=shared
        )

        n = 10000
        counts = {name: 0 for name in names}
        for i in range(n):
            worker = worker1 if i % 2 == 0 else worker2
            chosen = worker.get_provider("m1", providers)
            counts[chosen["id"]] += 1

        obs = _distribution(counts, n)
        expected = {name: w for name, w in zip(names, weights)}
        assert _close_enough(obs, expected, tol=0.03), (obs, expected)

    def test_independent_sequences_drive_selection(self):
        shared = FakeRedis()
        s = WeightedStrategy(models_config_path=_mk_path(), redis_client=shared)
        # next_sequence must be monotonic and shared
        seq = [s._counters.next_sequence("m") for _ in range(5)]
        assert seq == [0, 1, 2, 3, 4]
        # a second strategy on the same Redis continues the sequence
        s2 = WeightedStrategy(models_config_path=_mk_path(), redis_client=shared)
        assert s2._counters.next_sequence("m") == 5


# ---------------------------------------------------------------------------
# Balanced strategy: two workers, shared Redis → even global split
# ---------------------------------------------------------------------------
class TestBalancedGlobal:
    def test_two_workers_shared_redis_even_split(self):
        shared = FakeRedis()
        names = ["p-a", "p-b", "p-c"]
        providers = _providers([1.0] * 3, names)

        worker1 = LoadBalancedStrategy(
            models_config_path=_mk_path(), redis_client=shared
        )
        worker2 = LoadBalancedStrategy(
            models_config_path=_mk_path(), redis_client=shared
        )

        n = 3000
        counts = {name: 0 for name in names}
        for i in range(n):
            worker = worker1 if i % 2 == 0 else worker2
            chosen = worker.get_provider("m1", providers)
            counts[chosen["id"]] += 1

        # Even split across 3 providers → ~1/3 each, tight tolerance.
        expected = {name: 1 / 3 for name in names}
        obs = _distribution(counts, n)
        assert _close_enough(obs, expected, tol=0.02), (obs, expected)

    def test_single_provider_always_chosen(self):
        shared = FakeRedis()
        providers = _providers([1.0], ["only"])
        s = LoadBalancedStrategy(models_config_path=_mk_path(), redis_client=shared)
        for _ in range(5):
            assert s.get_provider("m", providers)["id"] == "only"


# ---------------------------------------------------------------------------
# In‑memory fallback (Redis down) must not break routing
# ---------------------------------------------------------------------------
class TestFallback:
    def test_weighted_falls_back_when_redis_down(self):
        shared = FakeRedis()
        shared._fail = True  # simulate a downed Redis
        names = ["p-a", "p-b"]
        providers = _providers([0.7, 0.3], names)
        s = WeightedStrategy(models_config_path=_mk_path(), redis_client=shared)
        # Routing must still succeed (in-memory counters take over).
        counts = {name: 0 for name in names}
        n = 2000
        for _ in range(n):
            counts[s.get_provider("m1", providers)["id"]] += 1
        obs = _distribution(counts, n)
        expected = {"p-a": 0.7, "p-b": 0.3}
        assert _close_enough(obs, expected, tol=0.05), (obs, expected)

    def test_balanced_falls_back_when_redis_down(self):
        shared = FakeRedis()
        shared._fail = True
        names = ["p-a", "p-b", "p-c"]
        providers = _providers([1.0] * 3, names)
        s = LoadBalancedStrategy(models_config_path=_mk_path(), redis_client=shared)
        counts = {name: 0 for name in names}
        n = 300
        for _ in range(n):
            counts[s.get_provider("m1", providers)["id"]] += 1
        # Should still distribute roughly evenly in memory.
        assert all(v > 0 for v in counts.values()), counts

    def test_no_redis_client_pure_memory(self):
        # No redis client at all → pure in-memory, still works.
        names = ["p-a", "p-b"]
        providers = _providers([0.5, 0.5], names)
        s = LoadBalancedStrategy(models_config_path=_mk_path())
        assert s.get_provider("m", providers) is not None


# ---------------------------------------------------------------------------
# Dynamic weighted (subclass) still works with shared counters
# ---------------------------------------------------------------------------
class TestDynamicWeightedGlobal:
    def test_two_workers_shared_redis(self):
        shared = FakeRedis()
        names = ["p-a", "p-b"]
        providers = _providers([0.8, 0.2], names)
        w1 = DynamicWeightedStrategy(
            models_config_path=_mk_path(), redis_client=shared
        )
        w2 = DynamicWeightedStrategy(
            models_config_path=_mk_path(), redis_client=shared
        )
        n = 10000
        counts = {name: 0 for name in names}
        for i in range(n):
            worker = w1 if i % 2 == 0 else w2
            counts[worker.get_provider("m1", providers)["id"]] += 1
        obs = _distribution(counts, n)
        assert _close_enough(obs, {"p-a": 0.8, "p-b": 0.2}, tol=0.03), obs


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
