"""
Unit tests for ``llm_router_api.core.lb.strategies.weighted``.

Covers the static :class:`WeightedStrategy` helpers (weight clamping,
deterministic unit offset, normalized weights, selection) and the
:class:`DynamicWeightedStrategy` runtime weight + latency-history API.
Config files are written to ``tmp_path``; no external services required.
"""

from __future__ import annotations

import json
import os
import time

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from llm_router_api.core.lb.strategies import weighted as weighted_module  # noqa: E402
from llm_router_api.core.lb.strategies.weighted import (  # noqa: E402
    DynamicWeightedStrategy,
    WeightedStrategy,
)


def _write_config(tmp_path) -> str:
    path = tmp_path / "models-config.json"
    path.write_text(
        json.dumps({"active_models": {}, "openapi": {}}), encoding="utf-8"
    )
    return str(path)


def _providers(weights, ids=None):
    ids = ids or [f"p{i}" for i in range(len(weights))]
    return [
        {"id": pid, "api_host": f"http://{pid}:8080", "weight": w}
        for pid, w in zip(ids, weights)
    ]


class TestClampWeight:
    @pytest.mark.parametrize(
        "raw, expected",
        [(-0.5, 0.0), (1.5, 1.0), (0.5, 0.5), ("0.5", 0.5), ("abc", 1.0)],
    )
    def test_clamping(self, raw, expected):
        assert WeightedStrategy._clamp_weight(raw) == expected

    def test_none_maps_to_default(self):
        # float(None) raises TypeError → default 1.0
        assert WeightedStrategy._clamp_weight(None) == 1.0


class TestStableUnit:
    def test_deterministic(self):
        assert (
            weighted_module._stable_unit("m", 5)
            == weighted_module._stable_unit("m", 5)
        )

    def test_range(self):
        for seq in range(10):
            value = weighted_module._stable_unit("model", seq)
            assert 0.0 <= value < 1.0

    def test_different_for_consecutive_seq(self):
        values = {weighted_module._stable_unit("model", i) for i in range(10)}
        assert len(values) == 10

    def test_model_dependent(self):
        assert weighted_module._stable_unit("a", 1) != weighted_module._stable_unit(
            "b", 1
        )


class TestNormalizedWeights:
    def test_normalizes_to_one(self, tmp_path):
        strategy = WeightedStrategy(_write_config(tmp_path))
        weights = strategy._normalized_weights(_providers([0.5, 0.5]))
        assert sum(weights) == pytest.approx(1.0)
        assert weights[0] == pytest.approx(0.5)
        assert weights[1] == pytest.approx(0.5)

        weights = strategy._normalized_weights(_providers([0.25, 0.75]))
        assert weights[0] == pytest.approx(0.25)
        assert weights[1] == pytest.approx(0.75)

    def test_zero_total_falls_back_uniform(self, tmp_path):
        strategy = WeightedStrategy(_write_config(tmp_path))
        weights = strategy._normalized_weights(_providers([0, 0, 0]))
        assert weights == [pytest.approx(1 / 3), pytest.approx(1 / 3),
                           pytest.approx(1 / 3)]

    def test_missing_weight_defaults_to_one(self, tmp_path):
        strategy = WeightedStrategy(_write_config(tmp_path))
        providers = [{"id": "a"}, {"id": "b", "weight": 0.5}]
        weights = strategy._normalized_weights(providers)
        assert weights == [pytest.approx(2 / 3), pytest.approx(1 / 3)]


class TestWeightedGetProvider:
    def test_empty_providers_raises(self, tmp_path):
        strategy = WeightedStrategy(_write_config(tmp_path))
        with pytest.raises(ValueError, match="No providers"):
            strategy.get_provider("m", [])

    def test_returns_one_of_providers(self, tmp_path):
        strategy = WeightedStrategy(_write_config(tmp_path))
        providers = _providers([1, 1])
        for _ in range(5):
            chosen = strategy.get_provider("m", providers)
            assert chosen in providers

    def test_zero_weight_provider_never_chosen(self, tmp_path):
        strategy = WeightedStrategy(_write_config(tmp_path))
        providers = _providers([0, 1], ids=["dead", "alive"])
        for _ in range(200):
            chosen = strategy.get_provider("m", providers)
            assert chosen["id"] == "alive"


class TestDynamicWeightedStrategy:
    def test_initial_providers_fill_dynamic_weights(self, tmp_path):
        strategy = DynamicWeightedStrategy(
            _write_config(tmp_path),
            initial_providers=[{"id": "a", "weight": 0.5}],
        )
        assert strategy._dynamic_weights == {"a": 0.5}

    def test_no_initial_providers(self, tmp_path):
        strategy = DynamicWeightedStrategy(_write_config(tmp_path))
        assert strategy._dynamic_weights == {}

    def test_set_weight_clamps(self, tmp_path):
        strategy = DynamicWeightedStrategy(_write_config(tmp_path))
        strategy.set_weight({"id": "a"}, 5.0)
        assert strategy._dynamic_weights["a"] == 1.0
        strategy.set_weight({"id": "a"}, -5.0)
        assert strategy._dynamic_weights["a"] == 0.0

    def test_set_weight_by_key(self, tmp_path):
        strategy = DynamicWeightedStrategy(_write_config(tmp_path))
        strategy.set_weight_by_key("pk", 0.25)
        assert strategy._dynamic_weights["pk"] == 0.25

    def test_dynamic_overrides_static(self, tmp_path):
        strategy = DynamicWeightedStrategy(_write_config(tmp_path))
        providers = _providers([1, 1])
        strategy.set_weight_by_key("p1", 1.0)
        strategy.set_weight_by_key("p0", 0.0)
        weights = strategy._normalized_weights(providers)
        assert weights == [0.0, 1.0]

    def test_get_provider_uses_dynamic_weights(self, tmp_path):
        strategy = DynamicWeightedStrategy(_write_config(tmp_path))
        providers = _providers([1, 1])
        strategy.set_weight_by_key("p0", 0.0)
        strategy.set_weight_by_key("p1", 1.0)
        for _ in range(50):
            assert strategy.get_provider("m", providers)["id"] == "p1"

    def test_latency_history(self, tmp_path):
        strategy = DynamicWeightedStrategy(_write_config(tmp_path))
        providers = _providers([0, 1])
        key = "p1"

        assert strategy.get_latency_history(key) == []

        strategy.get_provider("m", providers)  # first pick: no interval yet
        assert strategy.get_latency_history(key) == []

        time.sleep(0.01)
        strategy.get_provider("m", providers)  # second pick → interval
        history = strategy.get_latency_history(key)
        assert len(history) == 1
        assert history[0] >= 0.0

    def test_latency_history_maxlen(self, tmp_path):
        strategy = DynamicWeightedStrategy(
            _write_config(tmp_path), history_size=3
        )
        providers = _providers([0, 1])
        for _ in range(6):
            strategy.get_provider("m", providers)
        assert len(strategy.get_latency_history("p1")) == 3
