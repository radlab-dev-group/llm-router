"""
Unit tests for :mod:`llm_router_api.base.constants`.

The module evaluates its configuration **at import time** from the
environment, so the tests are split into three parts:

* :class:`TestImportedInvariants` – invariants that hold for the module
  imported by the test process (the suite prelude forces
  ``LLM_ROUTER_MINIMUM=1`` and ``LLM_ROUTER_AUTH_ENABLED=0``);
* :class:`TestStartAppVerificator` – the import‑time validation logic,
  exercised through the (name‑mangled) static checks with the module
  globals monkeypatched;
* :class:`TestEnvDrivenBehaviour` – the env → value transformations and
  the startup validation, executed in a **subprocess** with a fully
  controlled environment (all ``LLM_ROUTER_*`` variables stripped first)
  so ambient configuration cannot leak into the expectations.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from llm_router_api.base import constants  # noqa: E402
from llm_router_api.base.constants_base import (  # noqa: E402
    POSSIBLE_BALANCE_STRATEGIES,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

_VERIFIER = constants._StartAppVerificator


def _static(name: str):
    """Return a name‑mangled static check of ``_StartAppVerificator``."""
    return getattr(_VERIFIER, f"_StartAppVerificator__{name}")


def _langchain_plugin_available() -> bool:
    try:
        from llm_router_plugins.utils.rag.langchain_plugin import (  # noqa: F401
            LangchainRAGPlugin,
        )
        from llm_router_plugins.utils.rag.engine import (  # noqa: F401
            langchain,
        )
    except Exception:
        return False
    return True


LANGCHAIN_PLUGIN_AVAILABLE = _langchain_plugin_available()


class TestImportedInvariants:
    def test_service_as_proxy_is_true(self):
        # The suite prelude forces MINIMUM=1 (setdefault) and the module
        # import succeeded, so the proxy flag must be set.
        assert constants.SERVICE_AS_PROXY is True

    def test_auth_disabled_by_suite_prelude(self):
        assert constants.LLM_ROUTER_AUTH_ENABLED is False

    def test_balance_strategy_is_valid(self):
        # A failed import would mean the strategy check rejected it.
        assert constants.SERVER_BALANCE_STRATEGY in POSSIBLE_BALANCE_STRATEGIES

    def test_main_env_prefix_is_stable(self):
        assert constants._DontChangeMe.MAIN_ENV_PREFIX == "LLM_ROUTER_"

    def test_monitor_intervals_are_positive(self):
        assert constants.ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS > 0
        assert constants.KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS > 0
        assert constants.PROVIDER_MONITOR_INTERVAL_SECONDS > 0
        assert constants.PROVIDER_MONITOR_PING_TIMEOUT_SECONDS > 0

    def test_ping_timeout_is_float(self):
        assert (
            isinstance(constants.PROVIDER_MONITOR_PING_TIMEOUT_SECONDS, float)
            is True
        )

    def test_max_request_body_size_is_positive_int(self):
        assert isinstance(constants.MAX_REQUEST_BODY_SIZE, int)
        assert constants.MAX_REQUEST_BODY_SIZE > 0

    def test_pipelines_are_clean_string_lists_when_set(self):
        for name in (
            "MASKING_STRATEGY_PIPELINE",
            "GUARDRAIL_STRATEGY_PIPELINE_REQUEST",
            "GUARDRAIL_STRATEGY_PIPELINE_RESPONSE",
            "UTILS_PLUGINS_PIPELINE",
        ):
            value = getattr(constants, name)
            if value:
                assert isinstance(value, list)
                assert all(isinstance(item, str) and item for item in value)

    def test_memory_seed_file_points_inside_llm_router_dir(self):
        seed = constants.LLM_ROUTER_AUTH_MEMORY_SEED_FILE
        assert seed.endswith(".llm-router/configs/auth/memory-keys.json")


class TestVerifyIsAbleToInit:
    def test_rejects_non_proxy_mode(self, monkeypatch):
        monkeypatch.setattr(constants, "SERVICE_AS_PROXY", False)
        with pytest.raises(ValueError, match="LLM_ROUTER_MINIMUM"):
            _static("verify_is_able_to_init")()

    def test_accepts_proxy_mode(self, monkeypatch):
        monkeypatch.setattr(constants, "SERVICE_AS_PROXY", True)
        assert _static("verify_is_able_to_init")() is None


class TestVerifyBalancingStrategy:
    def test_rejects_unknown_strategy(self, monkeypatch):
        monkeypatch.setattr(constants, "SERVER_BALANCE_STRATEGY", "bogus")
        with pytest.raises(ValueError) as excinfo:
            _static("verify_balancing_strategy")()
        message = str(excinfo.value)
        assert "bogus" in message
        for strategy in POSSIBLE_BALANCE_STRATEGIES:
            assert strategy in message

    @pytest.mark.parametrize(
        "strategy",
        [
            "balanced",
            "weighted",
            "dynamic_weighted",
            "first_available",
            "first_available_optim",
        ],
    )
    def test_accepts_every_known_strategy(self, monkeypatch, strategy):
        monkeypatch.setattr(constants, "SERVER_BALANCE_STRATEGY", strategy)
        assert _static("verify_balancing_strategy")() is None


class TestVerifyMasking:
    def test_force_masking_requires_pipeline(self, monkeypatch):
        monkeypatch.setattr(constants, "FORCE_MASKING", True)
        monkeypatch.setattr(constants, "MASKING_STRATEGY_PIPELINE", "")
        with pytest.raises(ValueError, match="pipeline of masking strategies"):
            _static("verify_default_masking_strategy")()

    def test_force_masking_with_pipeline_is_ok(self, monkeypatch):
        monkeypatch.setattr(constants, "FORCE_MASKING", True)
        monkeypatch.setattr(constants, "MASKING_STRATEGY_PIPELINE", ["fast_masker"])
        assert _static("verify_default_masking_strategy")() is None

    def test_without_force_masking_pipeline_not_required(self, monkeypatch):
        monkeypatch.setattr(constants, "FORCE_MASKING", False)
        monkeypatch.setattr(constants, "MASKING_STRATEGY_PIPELINE", "")
        assert _static("verify_default_masking_strategy")() is None


class TestVerifyRequestGuardrails:
    def test_audit_requires_force_flag(self, monkeypatch):
        monkeypatch.setattr(constants, "GUARDRAIL_WITH_AUDIT_REQUEST", True)
        monkeypatch.setattr(constants, "FORCE_GUARDRAIL_REQUEST", False)
        with pytest.raises(ValueError, match="LLM_ROUTER_FORCE_GUARDRAIL_REQUEST"):
            _static("verify_default_request_guardrails")()

    def test_force_flag_requires_pipeline(self, monkeypatch):
        monkeypatch.setattr(constants, "GUARDRAIL_WITH_AUDIT_REQUEST", False)
        monkeypatch.setattr(constants, "FORCE_GUARDRAIL_REQUEST", True)
        monkeypatch.setattr(constants, "GUARDRAIL_STRATEGY_PIPELINE_REQUEST", "")
        with pytest.raises(ValueError, match="pipeline of guardrail strategies"):
            _static("verify_default_request_guardrails")()

    def test_full_setup_is_ok(self, monkeypatch):
        monkeypatch.setattr(constants, "GUARDRAIL_WITH_AUDIT_REQUEST", True)
        monkeypatch.setattr(constants, "FORCE_GUARDRAIL_REQUEST", True)
        monkeypatch.setattr(
            constants, "GUARDRAIL_STRATEGY_PIPELINE_REQUEST", ["gr1"]
        )
        assert _static("verify_default_request_guardrails")() is None

    def test_no_flags_no_pipeline_is_ok(self, monkeypatch):
        monkeypatch.setattr(constants, "GUARDRAIL_WITH_AUDIT_REQUEST", False)
        monkeypatch.setattr(constants, "FORCE_GUARDRAIL_REQUEST", False)
        monkeypatch.setattr(constants, "GUARDRAIL_STRATEGY_PIPELINE_REQUEST", "")
        assert _static("verify_default_request_guardrails")() is None


class TestVerifyResponseGuardrails:
    def test_audit_requires_force_flag(self, monkeypatch):
        monkeypatch.setattr(constants, "GUARDRAIL_WITH_AUDIT_RESPONSE", True)
        monkeypatch.setattr(constants, "FORCE_GUARDRAIL_RESPONSE", False)
        with pytest.raises(ValueError, match="LLM_ROUTER_FORCE_GUARDRAIL_RESPONSE"):
            _static("verify_default_response_guardrails")()

    def test_force_flag_requires_pipeline(self, monkeypatch):
        monkeypatch.setattr(constants, "GUARDRAIL_WITH_AUDIT_RESPONSE", False)
        monkeypatch.setattr(constants, "FORCE_GUARDRAIL_RESPONSE", True)
        monkeypatch.setattr(constants, "GUARDRAIL_STRATEGY_PIPELINE_RESPONSE", "")
        with pytest.raises(ValueError, match="pipeline of guardrail strategies"):
            _static("verify_default_response_guardrails")()

    def test_full_setup_is_ok(self, monkeypatch):
        monkeypatch.setattr(constants, "GUARDRAIL_WITH_AUDIT_RESPONSE", True)
        monkeypatch.setattr(constants, "FORCE_GUARDRAIL_RESPONSE", True)
        monkeypatch.setattr(
            constants, "GUARDRAIL_STRATEGY_PIPELINE_RESPONSE", ["gr2"]
        )
        assert _static("verify_default_response_guardrails")() is None


class TestVerifyUtilsPlugins:
    def test_empty_pipeline_skips_plugin_checks(self, monkeypatch):
        monkeypatch.setattr(constants, "UTILS_PLUGINS_PIPELINE", "")
        assert _VERIFIER()._StartAppVerificator__verify_utils_plugins() is None

    def test_pipeline_without_langchain_rag_is_noop(self, monkeypatch):
        monkeypatch.setattr(constants, "UTILS_PLUGINS_PIPELINE", ["other"])
        assert _VERIFIER()._StartAppVerificator__verify_utils_plugins() is None


@pytest.mark.skipif(
    not LANGCHAIN_PLUGIN_AVAILABLE,
    reason="langchain RAG plugin is not installed in this environment",
)
class TestVerifyLangchainRag:
    def _prepare(self, monkeypatch, **overrides) -> None:
        from llm_router_plugins.utils.rag.engine import langchain as lc
        from llm_router_plugins.utils.rag.langchain_plugin import (
            LangchainRAGPlugin,
        )

        monkeypatch.setattr(
            constants, "UTILS_PLUGINS_PIPELINE", [LangchainRAGPlugin.name]
        )
        defaults = {
            "LANGCHAIN_RAG_COLLECTION": "collection",
            "LANGCHAIN_RAG_EMBEDDER": "embedder",
            "LANGCHAIN_RAG_DEVICE": "cpu",
            "LANGCHAIN_RAG_CHUNK_SIZE": 400,
            "LANGCHAIN_RAG_CHUNK_OVERLAP": 100,
        }
        defaults.update(overrides)
        for name, value in defaults.items():
            monkeypatch.setattr(lc, name, value)

    def _check(self):
        verifier = _VERIFIER()
        check = verifier._StartAppVerificator__verify_utils_plugins_langchain_rag
        return check()

    def test_all_settings_present_is_ok(self, monkeypatch):
        self._prepare(monkeypatch)
        assert self._check() is None

    def test_missing_collection_rejected(self, monkeypatch):
        self._prepare(monkeypatch, LANGCHAIN_RAG_COLLECTION=None)
        with pytest.raises(ValueError, match="LANGCHAIN_RAG_COLLECTION"):
            self._check()

    def test_missing_embedder_rejected(self, monkeypatch):
        self._prepare(monkeypatch, LANGCHAIN_RAG_EMBEDDER="")
        with pytest.raises(ValueError, match="LANGCHAIN_RAG_EMBEDDER"):
            self._check()

    def test_missing_device_rejected(self, monkeypatch):
        self._prepare(monkeypatch, LANGCHAIN_RAG_DEVICE="")
        with pytest.raises(ValueError, match="LANGCHAIN_RAG_DEVICE"):
            self._check()

    def test_missing_chunk_size_rejected(self, monkeypatch):
        self._prepare(monkeypatch, LANGCHAIN_RAG_CHUNK_SIZE=0)
        with pytest.raises(ValueError, match="LLM_ROUTER_LANGCHAIN_RAG_CHUNK_SIZE"):
            self._check()

    def test_missing_chunk_overlap_rejected(self, monkeypatch):
        self._prepare(monkeypatch, LANGCHAIN_RAG_CHUNK_OVERLAP=0)
        with pytest.raises(
            ValueError, match="LLM_ROUTER_LANGCHAIN_RAG_CHUNK_OVERLAP"
        ):
            self._check()

    def test_plugin_not_in_pipeline_skips_checks(self, monkeypatch):
        from llm_router_plugins.utils.rag.engine import langchain as lc

        monkeypatch.setattr(constants, "UTILS_PLUGINS_PIPELINE", ["other"])
        monkeypatch.setattr(lc, "LANGCHAIN_RAG_COLLECTION", None)
        assert self._check() is None


class TestDontRunIfSomethingIsWrong:
    @pytest.fixture()
    def valid_config(self, monkeypatch) -> None:
        monkeypatch.setattr(constants, "SERVICE_AS_PROXY", True)
        monkeypatch.setattr(constants, "SERVER_BALANCE_STRATEGY", "balanced")
        monkeypatch.setattr(constants, "FORCE_MASKING", False)
        monkeypatch.setattr(constants, "MASKING_STRATEGY_PIPELINE", "")
        monkeypatch.setattr(constants, "GUARDRAIL_WITH_AUDIT_REQUEST", False)
        monkeypatch.setattr(constants, "FORCE_GUARDRAIL_REQUEST", False)
        monkeypatch.setattr(constants, "GUARDRAIL_STRATEGY_PIPELINE_REQUEST", "")
        monkeypatch.setattr(constants, "GUARDRAIL_WITH_AUDIT_RESPONSE", False)
        monkeypatch.setattr(constants, "FORCE_GUARDRAIL_RESPONSE", False)
        monkeypatch.setattr(constants, "GUARDRAIL_STRATEGY_PIPELINE_RESPONSE", "")
        monkeypatch.setattr(constants, "UTILS_PLUGINS_PIPELINE", "")

    def test_valid_configuration_passes(self, valid_config):
        assert _VERIFIER().dont_run_if_something_is_wrong() is None

    def test_first_check_failure_propagates(self, valid_config, monkeypatch):
        monkeypatch.setattr(constants, "SERVICE_AS_PROXY", False)
        with pytest.raises(ValueError, match="LLM_ROUTER_MINIMUM"):
            _VERIFIER().dont_run_if_something_is_wrong()

    def test_masking_failure_propagates(self, valid_config, monkeypatch):
        monkeypatch.setattr(constants, "FORCE_MASKING", True)
        with pytest.raises(ValueError, match="masking strategies"):
            _VERIFIER().dont_run_if_something_is_wrong()


# --------------------------------------------------------------------------- #
# Environment‑driven behaviour (subprocess with a controlled environment)
# --------------------------------------------------------------------------- #

_PROBE_SNIPPET = (
    "import json, os\n"
    "from llm_router_api.base import constants as c\n"
    "attrs = os.environ['PROBE_ATTRS'].split(',')\n"
    "print(json.dumps({a: getattr(c, a) for a in attrs}))\n"
)

_IMPORT_SNIPPET = "import llm_router_api.base.constants"

EXPECTED_DEFAULTS = {
    "PROMPTS_DIR": "resources/prompts",
    "MODELS_CONFIG_FILE": "resources/configs/models-config.json",
    "EXTERNAL_API_TIMEOUT": 300,
    "LLM_ROUTER_API_TIMEOUT": 0,
    "REST_API_LOG_FILE_NAME": "llm-router.log",
    "REST_API_LOG_LEVEL": "INFO",
    "LOG_TO_FILE": False,
    "REST_API_LOG_MAX_BYTES": 50 * 1024 * 1024,
    "REST_API_LOG_BACKUP_COUNT": 5,
    "DEFAULT_API_PREFIX": "/api",
    "SERVICE_AS_PROXY": True,
    "MAX_REQUEST_BODY_SIZE": 10 * 1024 * 1024,
    "SERVER_TYPE": "flask",
    "SERVER_PORT": 8080,
    "SERVER_WORKERS_COUNT": 2,
    "SERVER_THREADS_COUNT": 8,
    "SERVER_WORKERS_CLASS": None,
    "SERVER_HOST": "localhost",
    "RUN_IN_DEBUG_MODE": False,
    "USE_PROMETHEUS": False,
    "SERVER_BALANCE_STRATEGY": "balanced",
    "REDIS_HOST": "",
    "REDIS_PORT": 6379,
    "REDIS_DB": 0,
    "REDIS_PASSWORD": None,
    "REDIS_PROTOCOL": 3,
    "FORCE_MASKING": False,
    "MASKING_WITH_AUDIT": False,
    "MASKING_STRATEGY_PIPELINE": "",
    "FORCE_GUARDRAIL_REQUEST": False,
    "GUARDRAIL_WITH_AUDIT_REQUEST": False,
    "GUARDRAIL_STRATEGY_PIPELINE_REQUEST": "",
    "FORCE_GUARDRAIL_RESPONSE": False,
    "GUARDRAIL_WITH_AUDIT_RESPONSE": False,
    "GUARDRAIL_STRATEGY_PIPELINE_RESPONSE": "",
    "UTILS_PLUGINS_PIPELINE": "",
    "LLM_ROUTER_AUTH_ENABLED": False,
    "LLM_ROUTER_AUTH_KEY_STORE": "memory",
    "LLM_ROUTER_AUTH_VAULT_ADDR": "",
    "LLM_ROUTER_AUTH_VAULT_PATH": "secret/data/llm-router/api-keys",
    "LLM_ROUTER_AUTH_VAULT_AUTH_METHOD": "kubernetes",
    "LLM_ROUTER_AUTH_VAULT_ROLE_ID": "",
    "LLM_ROUTER_AUTH_VAULT_SECRET_ID": "",
    "LLM_ROUTER_AUTH_REDIS_HOST": "",
    "LLM_ROUTER_AUTH_REDIS_PORT": 6379,
    "LLM_ROUTER_AUTH_REDIS_DB": 0,
    "LLM_ROUTER_AUTH_REDIS_PASSWORD": None,
    "LLM_ROUTER_AUTH_REDIS_PROTOCOL": 3,
    "LLM_ROUTER_AUTH_KEY_CACHE_TTL": 300,
    "LLM_ROUTER_AUTH_KEY_CACHE_JITTER": 60,
    "LLM_ROUTER_AUTH_DEFAULT_RATE_LIMIT": 60,
    "LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS": "/metrics,/health",
    "LLM_ROUTER_TRUSTED_PROXIES": "",
    "LLM_ROUTER_AUTH_FAILURE_LIMIT": 20,
    "LLM_ROUTER_AUTH_KEY_PREFIX": "sk-llmr-live",
    "LLM_ROUTER_AUTH_KEY_LENGTH": 48,
    "LLM_ROUTER_AUTH_ROTATION_GRACE_PERIOD": 3600,
    "LLM_ROUTER_AUTH_AUDIT": False,
    "ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS": 5,
    "KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS": 1,
    "PROVIDER_MONITOR_INTERVAL_SECONDS": 5,
    "PROVIDER_MONITOR_PING_TIMEOUT_SECONDS": 5.0,
    "PROVIDER_MONITOR_MAX_CONSECUTIVE_FAILURES": 2,
}


def _clean_env(extra=None, minimum="1"):
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("LLM_ROUTER_")
    }
    if minimum is not None:
        env["LLM_ROUTER_MINIMUM"] = minimum
    env["LLM_ROUTER_AUTH_ENABLED"] = "0"
    if extra:
        env.update(extra)
    return env


def _run(snippet: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", snippet],
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(REPO_ROOT),
    )


def _probe(extra, attrs):
    env = _clean_env(extra)
    env["PROBE_ATTRS"] = ",".join(attrs)
    proc = _run(_PROBE_SNIPPET, env)
    assert proc.returncode == 0, f"import failed:\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _probe_import_fails(extra, *markers, minimum="1"):
    proc = _run(_IMPORT_SNIPPET, _clean_env(extra, minimum=minimum))
    assert proc.returncode != 0, f"import unexpectedly succeeded:\n{proc.stdout}"
    stderr = proc.stderr.lower()
    for marker in markers:
        assert (
            marker.lower() in stderr
        ), f"expected {marker!r} in stderr, got:\n{proc.stderr}"


class TestEnvDrivenBehaviour:
    def test_defaults_with_clean_environment(self):
        values = _probe(None, list(EXPECTED_DEFAULTS))
        assert values == EXPECTED_DEFAULTS

    def test_server_overrides(self):
        values = _probe(
            {
                "LLM_ROUTER_SERVER_PORT": "9090",
                "LLM_ROUTER_SERVER_WORKER_CLASS": "gevent",
                "LLM_ROUTER_SERVER_TYPE": "GUNICORN",
                "LLM_ROUTER_IN_DEBUG": "1",
                "LLM_ROUTER_MAX_REQUEST_BODY_SIZE": "1234",
            },
            [
                "SERVER_PORT",
                "SERVER_WORKERS_CLASS",
                "SERVER_TYPE",
                "RUN_IN_DEBUG_MODE",
                "REST_API_LOG_LEVEL",
                "MAX_REQUEST_BODY_SIZE",
            ],
        )
        assert values == {
            "SERVER_PORT": 9090,
            "SERVER_WORKERS_CLASS": "gevent",
            "SERVER_TYPE": "gunicorn",
            "RUN_IN_DEBUG_MODE": True,
            "REST_API_LOG_LEVEL": "DEBUG",
            "MAX_REQUEST_BODY_SIZE": 1234,
        }

    def test_redis_and_auth_redis_overrides(self):
        values = _probe(
            {
                "LLM_ROUTER_REDIS_PASSWORD": "s3cret",
                "LLM_ROUTER_REDIS_PORT": "6380",
                "LLM_ROUTER_REDIS_DB": "2",
                "LLM_ROUTER_REDIS_PROTOCOL": "2",
                "LLM_ROUTER_AUTH_REDIS_PASSWORD": "pw",
                "LLM_ROUTER_AUTH_REDIS_PORT": "7000",
                "LLM_ROUTER_AUTH_REDIS_DB": "3",
                "LLM_ROUTER_AUTH_REDIS_PROTOCOL": "2",
            },
            [
                "REDIS_PASSWORD",
                "REDIS_PORT",
                "REDIS_DB",
                "REDIS_PROTOCOL",
                "LLM_ROUTER_AUTH_REDIS_PASSWORD",
                "LLM_ROUTER_AUTH_REDIS_PORT",
                "LLM_ROUTER_AUTH_REDIS_DB",
                "LLM_ROUTER_AUTH_REDIS_PROTOCOL",
            ],
        )
        assert values == {
            "REDIS_PASSWORD": "s3cret",
            "REDIS_PORT": 6380,
            "REDIS_DB": 2,
            "REDIS_PROTOCOL": 2,
            "LLM_ROUTER_AUTH_REDIS_PASSWORD": "pw",
            "LLM_ROUTER_AUTH_REDIS_PORT": 7000,
            "LLM_ROUTER_AUTH_REDIS_DB": 3,
            "LLM_ROUTER_AUTH_REDIS_PROTOCOL": 2,
        }

    def test_pipeline_splitting_and_misc_overrides(self):
        values = _probe(
            {
                "LLM_ROUTER_UTILS_PLUGINS_PIPELINE": " a , b ,, c ",
                "LLM_ROUTER_MASKING_STRATEGY_PIPELINE": "fast_masker , genai",
                "LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_REQUEST": "g1,g2",
                "LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_RESPONSE": " r1 , r2 ",
                "LLM_ROUTER_EP_PREFIX": "/api/v2",
                "LLM_ROUTER_USE_PROMETHEUS": "1",
                "LLM_ROUTER_LOG_TO_FILE": "1",
                "LLM_ROUTER_BALANCE_STRATEGY": "first_available_optim",
            },
            [
                "UTILS_PLUGINS_PIPELINE",
                "MASKING_STRATEGY_PIPELINE",
                "GUARDRAIL_STRATEGY_PIPELINE_REQUEST",
                "GUARDRAIL_STRATEGY_PIPELINE_RESPONSE",
                "DEFAULT_API_PREFIX",
                "USE_PROMETHEUS",
                "LOG_TO_FILE",
                "SERVER_BALANCE_STRATEGY",
            ],
        )
        assert values == {
            "UTILS_PLUGINS_PIPELINE": ["a", "b", "c"],
            "MASKING_STRATEGY_PIPELINE": ["fast_masker", "genai"],
            "GUARDRAIL_STRATEGY_PIPELINE_REQUEST": ["g1", "g2"],
            "GUARDRAIL_STRATEGY_PIPELINE_RESPONSE": ["r1", "r2"],
            "DEFAULT_API_PREFIX": "/api/v2",
            "USE_PROMETHEUS": True,
            "LOG_TO_FILE": True,
            "SERVER_BALANCE_STRATEGY": "first_available_optim",
        }

    def test_auth_settings_overrides(self):
        values = _probe(
            {
                "LLM_ROUTER_AUTH_ENABLED": "true",
                "LLM_ROUTER_AUTH_KEY_STORE": "Vault",
                "LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS": "/a,/b",
                "LLM_ROUTER_AUTH_KEY_PREFIX": "sk-x",
                "LLM_ROUTER_AUTH_KEY_LENGTH": "32",
                "LLM_ROUTER_AUTH_FAILURE_LIMIT": "5",
            },
            [
                "LLM_ROUTER_AUTH_ENABLED",
                "LLM_ROUTER_AUTH_KEY_STORE",
                "LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS",
                "LLM_ROUTER_AUTH_KEY_PREFIX",
                "LLM_ROUTER_AUTH_KEY_LENGTH",
                "LLM_ROUTER_AUTH_FAILURE_LIMIT",
            ],
        )
        assert values == {
            "LLM_ROUTER_AUTH_ENABLED": True,
            "LLM_ROUTER_AUTH_KEY_STORE": "vault",
            "LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS": "/a,/b",
            "LLM_ROUTER_AUTH_KEY_PREFIX": "sk-x",
            "LLM_ROUTER_AUTH_KEY_LENGTH": 32,
            "LLM_ROUTER_AUTH_FAILURE_LIMIT": 5,
        }

    def test_monitoring_intervals_overrides(self):
        values = _probe(
            {
                "LLM_ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS": "7",
                "LLM_ROUTER_KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS": "2",
                "LLM_ROUTER_PROVIDER_MONITOR_INTERVAL_SECONDS": "9",
                "LLM_ROUTER_PROVIDER_MONITOR_PING_TIMEOUT_SECONDS": "7.5",
                "LLM_ROUTER_PROVIDER_MONITOR_MAX_CONSECUTIVE_FAILURES": "3",
            },
            [
                "ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS",
                "KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS",
                "PROVIDER_MONITOR_INTERVAL_SECONDS",
                "PROVIDER_MONITOR_PING_TIMEOUT_SECONDS",
                "PROVIDER_MONITOR_MAX_CONSECUTIVE_FAILURES",
            ],
        )
        assert values == {
            "ROUTER_SERVICES_MONITOR_INTERVAL_SECONDS": 7,
            "KEEPALIVE_MODEL_MONITOR_INTERVAL_SECONDS": 2,
            "PROVIDER_MONITOR_INTERVAL_SECONDS": 9,
            "PROVIDER_MONITOR_PING_TIMEOUT_SECONDS": 7.5,
            "PROVIDER_MONITOR_MAX_CONSECUTIVE_FAILURES": 3,
        }

    def test_truthy_alternatives_for_minimum(self):
        for truthy in ("yes", "tak"):
            values = _probe(
                {"LLM_ROUTER_MINIMUM": truthy},
                ["SERVICE_AS_PROXY"],
            )
            assert values == {"SERVICE_AS_PROXY": True}

    def test_masking_and_guardrails_happy_path_imports(self):
        values = _probe(
            {
                "LLM_ROUTER_FORCE_MASKING": "1",
                "LLM_ROUTER_MASKING_STRATEGY_PIPELINE": "fast_masker",
                "LLM_ROUTER_FORCE_GUARDRAIL_REQUEST": "1",
                "LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_REQUEST": "gr1",
                "LLM_ROUTER_GUARDRAIL_WITH_AUDIT_REQUEST": "1",
                "LLM_ROUTER_FORCE_GUARDRAIL_RESPONSE": "1",
                "LLM_ROUTER_GUARDRAIL_STRATEGY_PIPELINE_RESPONSE": "gr2",
                "LLM_ROUTER_GUARDRAIL_WITH_AUDIT_RESPONSE": "1",
            },
            [
                "FORCE_MASKING",
                "MASKING_STRATEGY_PIPELINE",
                "FORCE_GUARDRAIL_REQUEST",
                "GUARDRAIL_STRATEGY_PIPELINE_REQUEST",
                "GUARDRAIL_WITH_AUDIT_REQUEST",
                "FORCE_GUARDRAIL_RESPONSE",
                "GUARDRAIL_STRATEGY_PIPELINE_RESPONSE",
                "GUARDRAIL_WITH_AUDIT_RESPONSE",
            ],
        )
        assert values == {
            "FORCE_MASKING": True,
            "MASKING_STRATEGY_PIPELINE": ["fast_masker"],
            "FORCE_GUARDRAIL_REQUEST": True,
            "GUARDRAIL_STRATEGY_PIPELINE_REQUEST": ["gr1"],
            "GUARDRAIL_WITH_AUDIT_REQUEST": True,
            "FORCE_GUARDRAIL_RESPONSE": True,
            "GUARDRAIL_STRATEGY_PIPELINE_RESPONSE": ["gr2"],
            "GUARDRAIL_WITH_AUDIT_RESPONSE": True,
        }

    def test_missing_minimum_rejected(self):
        _probe_import_fails({}, "LLM_ROUTER_MINIMUM", minimum=None)

    def test_falsy_minimum_rejected(self):
        _probe_import_fails({"LLM_ROUTER_MINIMUM": "0"}, "LLM_ROUTER_MINIMUM")

    def test_unknown_balance_strategy_rejected(self):
        _probe_import_fails(
            {"LLM_ROUTER_BALANCE_STRATEGY": "bogus"},
            "not a valid strategy",
        )

    def test_force_masking_without_pipeline_rejected(self):
        _probe_import_fails(
            {"LLM_ROUTER_FORCE_MASKING": "1"},
            "pipeline of masking strategies",
        )

    def test_request_audit_without_force_flag_rejected(self):
        _probe_import_fails(
            {"LLM_ROUTER_GUARDRAIL_WITH_AUDIT_REQUEST": "1"},
            "LLM_ROUTER_FORCE_GUARDRAIL_REQUEST",
        )

    def test_request_force_flag_without_pipeline_rejected(self):
        _probe_import_fails(
            {"LLM_ROUTER_FORCE_GUARDRAIL_REQUEST": "1"},
            "pipeline of guardrail strategies",
        )

    def test_response_audit_without_force_flag_rejected(self):
        _probe_import_fails(
            {"LLM_ROUTER_GUARDRAIL_WITH_AUDIT_RESPONSE": "1"},
            "LLM_ROUTER_FORCE_GUARDRAIL_RESPONSE",
        )

    def test_response_force_flag_without_pipeline_rejected(self):
        _probe_import_fails(
            {"LLM_ROUTER_FORCE_GUARDRAIL_RESPONSE": "1"},
            "pipeline of guardrail strategies",
        )

    @pytest.mark.skipif(
        not LANGCHAIN_PLUGIN_AVAILABLE,
        reason="langchain RAG plugin is not installed in this environment",
    )
    def test_langchain_rag_without_collection_rejected(self):
        _probe_import_fails(
            {"LLM_ROUTER_UTILS_PLUGINS_PIPELINE": "langchain_rag"},
            "LANGCHAIN_RAG_COLLECTION",
        )
