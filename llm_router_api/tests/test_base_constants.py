"""
Unit tests for :mod:`llm_router_api.base.const_global` and
:mod:`llm_router_api.base.constants_base`.

Both modules are pure constants (no I/O), so the tests pin the contract
other packages rely on: the environment‑variable prefix, the load‑balancing
strategy identifiers and the provider name lists.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from llm_router_api.base import const_global  # noqa: E402
from llm_router_api.base.constants_base import (  # noqa: E402
    ALL_PROVIDERS,
    BalanceStrategies,
    OPENAI_COMPATIBLE_PROVIDERS,
    POSSIBLE_BALANCE_STRATEGIES,
    _DontChangeMe,
)


class TestConstGlobal:
    def test_is_cli_command_defaults_to_false(self):
        # The REST API process runs with CLI mode disabled; the CLI entry
        # point flips this flag before importing the router modules.
        assert const_global.IS_CLI_COMMAND is False


class TestEnvPrefix:
    def test_main_env_prefix(self):
        assert _DontChangeMe.MAIN_ENV_PREFIX == "LLM_ROUTER_"


class TestBalanceStrategies:
    def test_strategy_identifiers(self):
        assert BalanceStrategies.BALANCED == "balanced"
        assert BalanceStrategies.WEIGHTED == "weighted"
        assert BalanceStrategies.DYNAMIC_WEIGHTED == "dynamic_weighted"
        assert BalanceStrategies.FIRST_AVAILABLE == "first_available"
        assert BalanceStrategies.FIRST_AVAILABLE_OPTIM == "first_available_optim"

    def test_possible_balance_strategies_order_and_membership(self):
        assert POSSIBLE_BALANCE_STRATEGIES == [
            BalanceStrategies.BALANCED,
            BalanceStrategies.WEIGHTED,
            BalanceStrategies.DYNAMIC_WEIGHTED,
            BalanceStrategies.FIRST_AVAILABLE,
            BalanceStrategies.FIRST_AVAILABLE_OPTIM,
        ]

    def test_no_duplicate_strategy_identifiers(self):
        assert len(set(POSSIBLE_BALANCE_STRATEGIES)) == len(
            POSSIBLE_BALANCE_STRATEGIES
        )


class TestProviderLists:
    def test_openai_compatible_providers(self):
        assert OPENAI_COMPATIBLE_PROVIDERS == [
            "openai",
            "lmstudio",
            "vllm",
            "llama.cpp",
            "anthropic",
        ]

    def test_all_providers_composition(self):
        # ``ALL_PROVIDERS`` extends the OpenAI‑compatible list with Ollama
        # (and repeats ``anthropic`` — pin the exact composition).
        assert ALL_PROVIDERS == OPENAI_COMPATIBLE_PROVIDERS + [
            "ollama",
            "anthropic",
        ]

    def test_ollama_is_not_openai_compatible(self):
        assert "ollama" not in OPENAI_COMPATIBLE_PROVIDERS
        assert "ollama" in ALL_PROVIDERS

    def test_all_providers_cover_expected_universe(self):
        assert set(ALL_PROVIDERS) == {
            "openai",
            "lmstudio",
            "vllm",
            "llama.cpp",
            "anthropic",
            "ollama",
        }
