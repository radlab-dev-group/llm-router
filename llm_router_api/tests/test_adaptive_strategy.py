"""
Unit tests for ``llm_router_api.core.lb.strategies.beta.adaptive``.

Covers the adaptive (online-learning) strategy internals: provider-state
initialisation, EMA updates, cost prediction, softmax weight mapping,
provider selection, post‑choice learning and state export/import.
Uses a minimal model config in ``tmp_path``; no external services needed.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import time  # noqa: E402

import pytest  # noqa: E402

from llm_router_api.core.lb.strategies.beta.adaptive import (  # noqa: E402
    AdaptiveStrategy,
)


def _write_config(tmp_path) -> str:
    path = tmp_path / "models-config.json"
    path.write_text(
        json.dumps({"active_models": {}, "openapi": {}}), encoding="utf-8"
    )
    return str(path)


@pytest.fixture
def strategy(tmp_path) -> AdaptiveStrategy:
    return AdaptiveStrategy(_write_config(tmp_path))


class TestEnsureProviderState:
    def test_default_theta(self, strategy):
        strategy._ensure_provider_state("p1")
        assert strategy._theta["p1"] == [0.0, 0.0, 0.0, 0.0, 0.2, -0.2]
        assert strategy._ema_interval["p1"] == 0.0
        assert strategy._ema_trend["p1"] == 0.0
        assert strategy._recent_fail_rate["p1"] == 0.0
        assert strategy._last_interval["p1"] is None
        assert strategy._logits_ema["p1"] == 0.0

    def test_existing_theta_not_overwritten(self, strategy):
        strategy._ensure_provider_state("p1")
        strategy._theta["p1"][0] = 99.0
        strategy._ensure_provider_state("p1")
        assert strategy._theta["p1"][0] == 99.0


class TestEmaUpdate:
    def test_formula(self, strategy):
        assert strategy._ema_update(0.0, 1.0, 0.5) == 0.5
        assert strategy._ema_update(0.0, 1.0, 0.2) == 0.2

    def test_converges_to_value(self, strategy):
        ema = 0.0
        for _ in range(200):
            ema = strategy._ema_update(ema, 1.0, 0.3)
        assert ema == pytest.approx(1.0, abs=1e-3)

    def test_alpha_one_returns_value(self, strategy):
        assert strategy._ema_update(0.0, 0.7, 1.0) == 0.7


class TestPredictCost:
    def test_linear_combination(self, strategy):
        theta = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        x = [1.0, 1.0, 0.0, 0.0, 0.0, 0.0]
        # bias (1*1) + 2*1 = 3
        assert strategy._predict_cost(theta, x) == pytest.approx(3.0)

    def test_zero_features(self, strategy):
        theta = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        assert strategy._predict_cost(theta, [0] * 6) == 0.0


class TestSoftmaxWeights:
    def test_empty_returns_empty(self, strategy):
        assert strategy._softmax_weights([]) == []

    def test_sums_to_one(self, strategy):
        probs = strategy._softmax_weights([1.0, 2.0, 3.0])
        assert sum(probs) == pytest.approx(1.0)
        assert len(probs) == 3

    def test_higher_logit_higher_prob(self, strategy):
        probs = strategy._softmax_weights([0.0, 1.0, 2.0])
        assert probs[0] < probs[1] < probs[2]

    def test_p_min_enforced(self, strategy):
        strategy._p_min = 0.1
        probs = strategy._softmax_weights([100.0, 0.0, 0.0])
        assert min(probs) >= 0.1 - 1e-9
        assert sum(probs) == pytest.approx(1.0)

    def test_temperature_influence(self, strategy):
        strategy._p_min = 0.0  # avoid p_min clamping masking the effect
        logits = [0.0, 1.0]
        strategy._tau = 1.0
        flat = strategy._softmax_weights(logits)
        strategy._tau = 0.01
        sharp = strategy._softmax_weights(logits)
        # lower temperature → more concentrated distribution
        assert max(sharp) - min(sharp) > max(flat) - min(flat)


class TestGetProvider:
    def test_empty_raises(self, strategy):
        with pytest.raises(ValueError, match="No providers"):
            strategy.get_provider("m", [])

    def test_returns_a_known_provider(self, strategy):
        providers = [{"id": "a"}, {"id": "b"}]
        chosen = strategy.get_provider("m", providers)
        assert chosen in providers

    def test_theta_populated_after_calls(self, strategy):
        providers = [{"id": "a"}, {"id": "b"}]
        strategy.get_provider("m", providers)
        time.sleep(0.01)
        strategy.get_provider("m", providers)
        assert len(strategy._theta) >= 1
        for vec in strategy._theta.values():
            assert len(vec) == 6


class TestOnAfterChoice:
    def test_short_interval_sets_fail_flag(self, strategy):
        key = "p1"
        strategy._ensure_provider_state(key)
        # very recent prior choice → interval < 0.5s → fail flag
        strategy._last_chosen_time[key] = time.time() - 0.1
        before = strategy._recent_fail_rate[key]
        strategy._on_after_choice(key, time.time())
        assert strategy._recent_fail_rate[key] > before

    def test_worsening_interval_updates_ema(self, strategy):
        key = "p1"
        strategy._ensure_provider_state(key)
        strategy._last_chosen_time[key] = time.time() - 2.0
        strategy._last_interval[key] = 0.1
        before_ema = strategy._ema_interval[key]
        strategy._on_after_choice(key, time.time())
        assert strategy._ema_interval[key] != before_ema
        assert strategy._last_interval[key] > 0.1

    def test_first_choice_no_learning(self, strategy):
        key = "p1"
        strategy._ensure_provider_state(key)
        theta_before = list(strategy._theta[key])
        strategy._on_after_choice(key, time.time())
        # no previous timestamp → no interval → theta untouched
        assert strategy._theta[key] == theta_before
        assert strategy._last_interval[key] is None


class TestExportImport:
    def test_round_trip(self, strategy, tmp_path):
        strategy._theta["p1"] = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        strategy._ema_interval["p1"] = 0.5
        strategy._ema_trend["p1"] = 0.25
        state = strategy.export_state()

        other = AdaptiveStrategy(_write_config(tmp_path))
        other.import_state(state)
        assert other._theta["p1"] == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]
        assert other._ema_interval["p1"] == 0.5
        assert other._ema_trend["p1"] == 0.25

    def test_partial_import_keeps_defaults(self, strategy):
        defaults = {
            "lr": strategy._lr,
            "tau": strategy._tau,
            "p_min": strategy._p_min,
            "lambda_fail": strategy._lambda_fail,
            "lambda_bad": strategy._lambda_bad,
            "delta_bad": strategy._delta_bad,
            "ema_alpha_interval": strategy._ema_alpha_interval,
            "ema_alpha_fail": strategy._ema_alpha_fail,
            "ema_alpha_trend": strategy._ema_alpha_trend,
        }
        strategy.import_state({"theta": {"p1": [1, 1, 1, 1, 1, 1]}})
        assert strategy._theta == {"p1": [1, 1, 1, 1, 1, 1]}
        assert strategy._ema_interval == {}
        assert strategy._lr == defaults["lr"]
        assert strategy._tau == defaults["tau"]
        assert strategy._p_min == defaults["p_min"]
        assert strategy._lambda_fail == defaults["lambda_fail"]
        assert strategy._lambda_bad == defaults["lambda_bad"]
        assert strategy._delta_bad == defaults["delta_bad"]
        assert strategy._ema_alpha_interval == defaults["ema_alpha_interval"]
        assert strategy._ema_alpha_fail == defaults["ema_alpha_fail"]
        assert strategy._ema_alpha_trend == defaults["ema_alpha_trend"]

    def test_explicit_hyperparameters_imported(self, strategy):
        strategy.import_state({"lr": 0.5, "tau": 2.0, "p_min": 0.3})
        assert strategy._lr == 0.5
        assert strategy._tau == 2.0
        assert strategy._p_min == 0.3
