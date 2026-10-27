"""
Unit tests for :mod:`llm_router_api.base.const_global` and
:mod:`llm_router_api.base.constants_base`.

Both modules are pure constants (no I/O), so the tests pin the contract
other packages rely on: the environment‑variable prefix, the load‑balancing
strategy identifiers and the provider name lists.
"""

from __future__ import annotations

import importlib
import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from llm_router_api.base import const_global  # noqa: E402
from llm_router_api.base.constants_base import (  # noqa: E402
    ALL_PROVIDERS,
    BalanceStrategies,
    OPENAI_COMPATIBLE_PROVIDERS,
    AZURE_OPENAI_PROVIDER,
    POSSIBLE_BALANCE_STRATEGIES,
    _DontChangeMe,
)


class TestConstGlobal:
    def test_is_cli_command_defaults_to_false(self):
        # The REST API process runs with CLI mode disabled; the CLI entry
        # point flips this flag before importing the router modules.  The flag
        # lives in a shared module, and collecting ``llm_router_cli`` in the
        # same pytest session (as a combined api+lib+cli run does) imports
        # ``llm_router_cli.cli`` and flips it at import time — so reload the
        # module to assert its own default, then restore the session value.
        original = const_global.IS_CLI_COMMAND
        try:
            importlib.reload(const_global)
            assert const_global.IS_CLI_COMMAND is False
        finally:
            const_global.IS_CLI_COMMAND = original


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
        assert (
            BalanceStrategies.FIRST_AVAILABLE_NWORKERS
            == "first_available_optim_nworkers"
        )

    def test_possible_balance_strategies_order_and_membership(self):
        assert POSSIBLE_BALANCE_STRATEGIES == [
            BalanceStrategies.BALANCED,
            BalanceStrategies.WEIGHTED,
            BalanceStrategies.DYNAMIC_WEIGHTED,
            BalanceStrategies.FIRST_AVAILABLE,
            BalanceStrategies.FIRST_AVAILABLE_OPTIM,
            BalanceStrategies.FIRST_AVAILABLE_NWORKERS,
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
            AZURE_OPENAI_PROVIDER,
        ]

    def test_all_providers_composition(self):
        # ``ALL_PROVIDERS`` extends the OpenAI‑compatible list with Ollama,
        # Vertex AI and Bedrock (pin the exact composition).
        assert ALL_PROVIDERS == (
            OPENAI_COMPATIBLE_PROVIDERS + ["ollama", "vertex_ai", "bedrock"]
        )

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
            "vertex_ai",
            "bedrock",
            "azure_openai",
        }

    def test_azure_openai_is_openai_compatible_on_the_wire(self):
        # Azure OpenAI speaks the OpenAI bodies, responses and SSE stream;
        # only the addressing (deployment + api-version) and the auth
        # (api-key / Entra ID) differ, which the request adapter of the type
        # handles.
        assert "azure_openai" in OPENAI_COMPATIBLE_PROVIDERS
        assert "azure_openai" in ALL_PROVIDERS

    def test_bedrock_is_not_openai_compatible(self):
        # Bedrock speaks Converse and signs with SigV4: treating it as an
        # OpenAI‑compatible backend would send it an OpenAI body.
        assert "bedrock" not in OPENAI_COMPATIBLE_PROVIDERS
        assert "bedrock" in ALL_PROVIDERS
