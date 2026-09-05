"""
Unit tests for :class:`llm_router_api.endpoints.passthrough.PassthroughI`.

``PassthroughI`` is abstract (it inherits the abstract ``prepare_payload``
contract from ``EndpointI`` and implements it as a pass‑through), so the
tests exercise it through a minimal concrete subclass.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from llm_router_api.endpoints.passthrough import PassthroughI  # noqa: E402


class _ConcretePassthrough(PassthroughI):
    """Minimal concrete endpoint hosting the pass‑through behaviour."""

    def __init__(self):
        super().__init__(
            logger_file_name=None,
            logger_level="INFO",
            model_handler=None,
            prompt_handler=None,
            ep_name="passthrough_ep",
            method="POST",
            api_types=["builtin"],
            dont_add_api_prefix=False,
            direct_return=True,
        )


class TestPassthroughIAttributes:
    def test_class_argument_defaults_are_none(self):
        assert PassthroughI.REQUIRED_ARGS is None
        assert PassthroughI.OPTIONAL_ARGS is None
        assert PassthroughI.SYSTEM_PROMPT_NAME is None

    def test_registration_defaults(self):
        ep = _ConcretePassthrough()
        assert ep.name == "passthrough_ep"
        assert ep.method == "POST"
        assert ep._ep_types_str == ["builtin"]
        assert ep._dont_add_api_prefix is False
        assert ep.direct_return is True

    def test_one_request_per_user_message_disabled(self):
        # ``PassthroughI`` always forwards the whole payload at once.
        ep = _ConcretePassthrough()
        assert ep._call_for_each_user_msg is False

    def test_prepare_response_function_unset_by_default(self):
        ep = _ConcretePassthrough()
        assert ep.prepare_response_function is None


class TestPassthroughIPreparePayload:
    def test_none_params_return_empty_dict(self):
        ep = _ConcretePassthrough()
        out = ep.prepare_payload(None)
        # ``response_time`` is injected by the ``@EP.response_time`` wrapper
        assert out == {"response_time": out["response_time"]}
        assert isinstance(out["response_time"], float)

    def test_dict_params_returned_unchanged(self):
        ep = _ConcretePassthrough()
        params = {"model": "m", "messages": [{"role": "user", "content": "x"}]}
        out = ep.prepare_payload(params)
        assert out["model"] == "m"
        assert out["messages"] == params["messages"]
        assert "response_time" in out

    def test_input_dict_not_mutated_by_response_time(self):
        ep = _ConcretePassthrough()
        params = {"a": 1}
        out = ep.prepare_payload(params)
        assert "response_time" not in params
        assert "response_time" in out
        assert out is not params
