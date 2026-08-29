"""
Tests for FirstAvailableStrategy timeout behavior.

Regression test: when no provider is active (all unhealthy, or health data
missing), ``get_provider`` looped forever because the empty-providers early
return (``return None``) was evaluated *before* the overall-timeout check in
``_acquire_provider_step``.  The documented ``TimeoutError`` was therefore
unreachable in exactly the situation it was meant for.

The strategy is exercised in isolation (no Redis): only the attributes used
by the acquisition loop are stubbed.
"""

from __future__ import annotations

import os
import threading
from types import SimpleNamespace

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest

from llm_router_api.core.lb.strategies.first_available import FirstAvailableStrategy


def make_isolated_strategy(timeout: float = 0.5) -> FirstAvailableStrategy:
    """
    Build a strategy instance without running the constructor (no Redis,
    no monitor threads) and stub the attributes used by the acquire loop.
    """

    strategy = FirstAvailableStrategy.__new__(FirstAvailableStrategy)
    strategy.timeout = timeout
    strategy.redis_health_check = SimpleNamespace(check_interval=0.02)
    strategy._get_active_providers = lambda model_name, providers: []
    strategy.init_provider = lambda model_name, providers, options=None: (
        "model:test",
        False,
    )
    return strategy


class TestFirstAvailableTimeout:
    """Timeout semantics of the provider-acquisition loop."""

    def test_no_active_providers_raises_timeout_error(self):
        """
        With an empty active-provider list the loop must raise
        ``TimeoutError`` after the budget is exhausted — not spin forever.

        The call runs in a daemon thread with a join timeout so a
        regression to the old infinite loop fails the test instead of
        hanging the suite.
        """

        strategy = make_isolated_strategy(timeout=0.3)
        outcome: dict = {}

        def runner():
            try:
                strategy.get_provider("test-model", [{"name": "p1"}])
            except TimeoutError as exc:
                outcome["error"] = exc
            else:
                outcome["provider"] = "should not happen"

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(timeout=10)

        assert (
            not thread.is_alive() or "error" in outcome
        ), "get_provider() never returned nor raised — infinite loop"
        assert "error" in outcome, f"expected TimeoutError, got outcome={outcome!r}"
        assert "test-model" in str(outcome["error"])

    def test_timeout_checked_even_when_providers_missing(self):
        """
        Unit-level: a single ``_acquire_provider_step`` past the budget must
        raise before the empty-providers short-circuit is reached.
        """

        import time

        strategy = make_isolated_strategy(timeout=0.0)
        with pytest.raises(TimeoutError):
            strategy._acquire_provider_step(
                model_name="test-model",
                providers=[{"name": "p1"}],
                is_random=False,
                redis_key="model:test",
                start_time=time.time() - 1.0,  # budget already exhausted
            )
