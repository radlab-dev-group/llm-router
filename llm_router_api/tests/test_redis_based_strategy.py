"""
Unit tests for ``llm_router_api.core.lb.redis_based_interface.RedisBasedStrategy``.

The abstract strategy is exercised in isolation: a concrete test-only
subclass (implementing the abstract ``get_provider``) is instantiated with
``__new__`` so the Redis/monitor-heavy constructor is skipped, then the
attributes used by the methods under test are stubbed.  Redis state is
simulated with ``fakeredis`` and the Lua acquire/release scripts are mocked
(``lupa`` is not installed, so fakeredis cannot execute them).
"""

from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from unittest import mock  # noqa: E402

import fakeredis  # noqa: E402

from llm_router_api.core.lb.redis_based_interface import (  # noqa: E402
    RedisBasedStrategy,
)


class _ConcreteRedisStrategy(RedisBasedStrategy):
    """Minimal concrete subclass so the class can be instantiated."""

    def get_provider(self, model_name, providers, options=None):
        return providers[0] if providers else None


def _make(
    acquire_result: int = 1, acquire_side_effect=None
) -> _ConcreteRedisStrategy:
    strategy = _ConcreteRedisStrategy.__new__(_ConcreteRedisStrategy)
    strategy.redis_client = fakeredis.FakeRedis(decode_responses=True)
    strategy.logger = mock.Mock()
    strategy.redis_health_check = mock.Mock()
    if acquire_side_effect is not None:
        strategy._acquire_script = mock.Mock(side_effect=acquire_side_effect)
    else:
        strategy._acquire_script = mock.Mock(return_value=acquire_result)
    strategy._release_script = mock.Mock(return_value=1)
    return strategy


def _providers():
    return [{"id": "p1"}, {"id": "p2"}]


class TestKeyHelpers:
    def test_get_redis_key(self):
        strategy = _make()
        assert strategy._get_redis_key("gpt4") == "model:gpt4"

    def test_get_redis_key_sanitized(self):
        strategy = _make()
        assert strategy._get_redis_key("a/b:c") == "model:a_b_c"

    def test_host_key(self):
        strategy = _make()
        assert strategy._host_key("my_server:01") == "host:my_server_01"

    def test_provider_field(self):
        strategy = _make()
        assert strategy._provider_field({"id": "p1"}) == "p1:is_chosen"

    def test_provider_field_sanitized(self):
        strategy = _make()
        assert strategy._provider_field({"id": "a/b"}) == "a_b:is_chosen"

    def test_init_flag(self):
        strategy = _make()
        assert strategy._init_flag("m") == "model:m:initialized"


class TestInitProvider:
    def test_empty_providers(self):
        strategy = _make()
        redis_key, is_random = strategy.init_provider("m", [])
        assert redis_key is None
        assert not is_random

    def test_registers_with_health_check(self):
        strategy = _make()
        providers = _providers()
        strategy.init_provider("m", providers)
        strategy.redis_health_check.add_providers.assert_called_once_with(
            "m", providers
        )

    def test_creates_fields_when_missing(self):
        strategy = _make()
        providers = _providers()
        redis_key, _ = strategy.init_provider("m", providers)
        assert strategy.redis_client.hget(redis_key, "p1:is_chosen") == "false"
        assert strategy.redis_client.hget(redis_key, "p2:is_chosen") == "false"

    def test_does_not_overwrite_existing_hash(self):
        strategy = _make()
        providers = _providers()
        # simulate an existing hash with a live lock
        strategy.redis_client.hset("model:m", "p1:is_chosen", "true")
        strategy.init_provider("m", providers)
        # existing lock preserved because the hash already existed
        assert strategy.redis_client.hget("model:m", "p1:is_chosen") == "true"

    def test_random_choice_option(self):
        strategy = _make()
        _, is_random = strategy.init_provider(
            "m", _providers(), options={"random_choice": True}
        )
        assert is_random is True

    def test_no_options_returns_falsy(self):
        strategy = _make()
        _, is_random = strategy.init_provider("m", _providers())
        assert not is_random


class TestTryAcquireRandomProvider:
    def test_success_sets_chosen_field(self):
        strategy = _make(acquire_result=1)
        providers = _providers()
        chosen = strategy._try_acquire_random_provider("model:m", providers)
        assert chosen is not None
        assert chosen["__chosen_field"].endswith(":is_chosen")
        strategy._acquire_script.assert_called()

    def test_all_locked_returns_none(self):
        strategy = _make(acquire_result=0)
        providers = _providers()
        assert strategy._try_acquire_random_provider("model:m", providers) is None

    def test_script_exception_skips_provider(self):
        def side_effect(keys=None, args=None):
            if args and args[0] == "p1:is_chosen":
                raise RuntimeError("redis down")
            return 1

        strategy = _make(acquire_side_effect=side_effect)
        providers = _providers()
        chosen = strategy._try_acquire_random_provider("model:m", providers)
        # p1 raises → skipped, p2 acquired
        assert chosen is not None
        assert chosen["id"] == "p2"

    def test_original_list_not_reordered(self):
        strategy = _make(acquire_result=1)
        providers = _providers()
        snapshot = [p["id"] for p in providers]
        strategy._try_acquire_random_provider("model:m", providers)
        assert [p["id"] for p in providers] == snapshot


class TestInitializeProviders:
    def test_creates_fields_and_flag(self):
        strategy = _make()
        strategy._initialize_providers("m", _providers())
        assert strategy.redis_client.hget("model:m", "p1:is_chosen") == "false"
        assert strategy.redis_client.get("model:m:initialized") == "1"

    def test_idempotent_preserves_lock(self):
        strategy = _make()
        providers = _providers()
        strategy._initialize_providers("m", providers)
        # simulate a live lock after init
        strategy.redis_client.hset("model:m", "p1:is_chosen", "true")
        # second call must not clobber the lock
        strategy._initialize_providers("m", providers)
        assert strategy.redis_client.hget("model:m", "p1:is_chosen") == "true"


class TestClearBuffers:
    def _make_with_config(self, model_path=""):
        strategy = _make()
        provider = {"id": "p1"}
        if model_path:
            provider["model_path"] = model_path
        strategy._api_model_config = SimpleNamespace(
            active_models={"openapi": ["m1"]},
            models_configs={"m1": {"providers": [provider]}},
        )
        return strategy

    def test_resets_fields(self):
        strategy = self._make_with_config()
        strategy.redis_client.hset("model:m1", "p1:is_chosen", "true")
        strategy._clear_buffers()
        assert strategy.redis_client.hget("model:m1", "p1:is_chosen") == "false"
        assert strategy.redis_client.get("model:m1:initialized") == "1"

    def test_model_path_renames_key(self):
        strategy = self._make_with_config(model_path="/models/x")
        strategy._clear_buffers()
        # key is derived from the model_path
        assert (
            strategy.redis_client.hget("model:_models_x", "p1:is_chosen") == "false"
        )


class TestGetActiveProviders:
    def test_delegates_only_active(self):
        strategy = _make()
        strategy.redis_health_check.get_providers.return_value = [{"id": "p1"}]
        result = strategy._get_active_providers("m", _providers())
        assert result == [{"id": "p1"}]
        strategy.redis_health_check.get_providers.assert_called_once_with(
            model_name="m", only_active=True
        )


class TestPrintProviderStatus:
    def test_logs_free_and_locked(self):
        strategy = _make()
        providers = _providers()
        strategy.redis_client.hset("model:m", "p1:is_chosen", "true")
        strategy.redis_client.hset("model:m", "p2:is_chosen", "false")
        strategy._print_provider_status("model:m", providers)
        text = " ".join(
            str(call.args) for call in strategy.logger.info.call_args_list
        )
        assert "locked" in text
        assert "free" in text

    def test_hgetall_error_path_logs_warning(self):
        strategy = _make()
        strategy.redis_client.hgetall = mock.Mock(side_effect=RuntimeError("boom"))
        # must not raise; log a warning instead
        strategy._print_provider_status("model:m", _providers())
        strategy.logger.warning.assert_called()
