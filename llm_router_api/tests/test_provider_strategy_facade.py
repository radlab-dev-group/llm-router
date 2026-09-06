"""
Unit tests for ``llm_router_api.core.lb.provider_strategy_facade``.

Covers the :class:`ProviderStrategyFacade` strategy resolution, the
``STRATEGIES`` registry, the shared-Redis-client builder and the
``ChooseProviderStrategyI._provider_key`` helper.
Config files are written to ``tmp_path``; no external services required.
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")
os.environ.setdefault("LLM_ROUTER_REDIS_HOST", "")

from unittest import mock  # noqa: E402

import pytest  # noqa: E402

import llm_router_api.base.constants as constants  # noqa: E402
from llm_router_api.base.constants_base import BalanceStrategies  # noqa: E402
from llm_router_api.core.lb import (
    provider_strategy_facade as facade_module,
)  # noqa: E402
from llm_router_api.core.lb.provider_strategy_facade import (  # noqa: E402
    ProviderStrategyFacade,
    STRATEGIES,
)
from llm_router_api.core.lb.strategies.balanced import (
    LoadBalancedStrategy,
)  # noqa: E402
from llm_router_api.core.lb.strategies.first_available import (  # noqa: E402
    FirstAvailableStrategy,
)
from llm_router_api.core.lb.strategies.first_available_optim import (  # noqa: E402
    FirstAvailableOptimStrategy,
)
from llm_router_api.core.lb.strategies.weighted import (  # noqa: E402
    DynamicWeightedStrategy,
    WeightedStrategy,
)
from llm_router_api.core.lb.strategy_interface import (
    ChooseProviderStrategyI,
)  # noqa: E402


def _write_config(tmp_path) -> str:
    path = tmp_path / "models-config.json"
    path.write_text(
        json.dumps({"active_models": {}, "openapi": {}}), encoding="utf-8"
    )
    return str(path)


def _facade(tmp_path, **kwargs) -> ProviderStrategyFacade:
    return ProviderStrategyFacade(_write_config(tmp_path), **kwargs)


class TestStrategiesRegistry:
    def test_all_five_strategies_registered(self):
        assert STRATEGIES[BalanceStrategies.BALANCED] is LoadBalancedStrategy
        assert STRATEGIES[BalanceStrategies.WEIGHTED] is WeightedStrategy
        assert (
            STRATEGIES[BalanceStrategies.DYNAMIC_WEIGHTED] is DynamicWeightedStrategy
        )
        assert (
            STRATEGIES[BalanceStrategies.FIRST_AVAILABLE] is FirstAvailableStrategy
        )
        assert (
            STRATEGIES[BalanceStrategies.FIRST_AVAILABLE_OPTIM]
            is FirstAvailableOptimStrategy
        )


class TestBuildSharedRedisClient:
    def test_no_host_returns_none(self, monkeypatch):
        monkeypatch.setattr(constants, "REDIS_HOST", "")
        assert facade_module._build_shared_redis_client() is None

    def test_host_set_returns_redis_client(self, monkeypatch):
        monkeypatch.setattr(constants, "REDIS_HOST", "localhost")
        client = facade_module._build_shared_redis_client()
        assert client is not None
        assert client.connection_pool.connection_kwargs["host"] == "localhost"


class TestInitResolution:
    def test_explicit_strategy_wins(self, tmp_path):
        strategy = mock.Mock()
        facade = _facade(tmp_path, strategy=strategy)
        assert facade.strategy is strategy

    def test_name_weighted(self, tmp_path):
        facade = _facade(tmp_path, strategy_name="weighted")
        assert isinstance(facade.strategy, WeightedStrategy)

    def test_name_dynamic_weighted(self, tmp_path):
        facade = _facade(tmp_path, strategy_name="dynamic_weighted")
        assert isinstance(facade.strategy, DynamicWeightedStrategy)

    def test_name_balanced(self, tmp_path):
        facade = _facade(tmp_path, strategy_name="balanced")
        assert isinstance(facade.strategy, LoadBalancedStrategy)

    def test_no_name_defaults_to_balanced(self, tmp_path):
        facade = _facade(tmp_path)
        assert isinstance(facade.strategy, LoadBalancedStrategy)

    def test_unknown_name_raises(self, tmp_path):
        with pytest.raises(RuntimeError, match="not found"):
            _facade(tmp_path, strategy_name="nope")


class TestFacadeCalls:
    def test_get_provider_empty_raises(self, tmp_path):
        facade = _facade(tmp_path)
        with pytest.raises(RuntimeError, match="does not have any providers"):
            facade.get_provider("m", [])

    def test_get_provider_delegates(self, tmp_path):
        facade = _facade(tmp_path)
        facade.strategy = mock.Mock()
        facade.strategy.get_provider.return_value = {"id": "p1"}

        providers = [{"id": "p1"}]
        result = facade.get_provider("m", providers, options={"x": 1})

        assert result == {"id": "p1"}
        facade.strategy.get_provider.assert_called_once_with(
            model_name="m", providers=providers, options={"x": 1}
        )

    def test_get_provider_records_lb_metric(self, tmp_path):
        facade = _facade(tmp_path, strategy_name="weighted")
        facade.strategy = mock.Mock()
        facade.strategy.get_provider.return_value = {"id": "p1"}
        router_metrics = mock.Mock()
        facade.set_router_metrics(router_metrics)

        facade.get_provider("m", [{"id": "p1"}])
        router_metrics.record_lb_strategy.assert_called_once_with(
            strategy="weighted", model_name="m"
        )

    def test_metrics_exception_swallowed(self, tmp_path):
        facade = _facade(tmp_path)
        facade.strategy = mock.Mock()
        facade.strategy.get_provider.return_value = {"id": "p1"}
        router_metrics = mock.Mock()
        router_metrics.record_lb_strategy.side_effect = RuntimeError("boom")
        facade.set_router_metrics(router_metrics)

        result = facade.get_provider("m", [{"id": "p1"}])
        assert result == {"id": "p1"}

    def test_put_provider_forwards(self, tmp_path):
        facade = _facade(tmp_path)
        facade.strategy = mock.Mock()
        provider = {"id": "p1"}
        facade.put_provider("m", provider, options={"force_update": True})
        facade.strategy.put_provider.assert_called_once_with(
            model_name="m", provider=provider, options={"force_update": True}
        )


class TestProviderKey:
    def _instance(self):
        # concrete subclass instance without running the constructor –
        # _provider_key only uses class-level state (REPLACE_PROVIDER_KEY)
        instance = LoadBalancedStrategy.__new__(LoadBalancedStrategy)
        return instance

    def test_id_preferred_over_api_host(self):
        provider_key = self._instance()._provider_key(
            {"id": "my.id", "api_host": "h1"}
        )
        # id wins; the '.' is sanitised to '_'
        assert provider_key == "my_id"

    def test_api_host_fallback(self):
        provider_key = self._instance()._provider_key({"api_host": "host-1"})
        assert provider_key == "host_1"

    def test_unknown_fallback(self):
        assert self._instance()._provider_key({}) == "unknown"

    def test_special_chars_sanitized(self):
        provider_key = self._instance()._provider_key({"id": "a/b:c.d,e;f\ng"})
        for ch in ChooseProviderStrategyI.REPLACE_PROVIDER_KEY:
            assert ch not in provider_key
        assert provider_key == "a_b_c_d_e_f_g"
