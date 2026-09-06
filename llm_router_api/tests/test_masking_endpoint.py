"""
Unit tests for the ``FastTextMasking`` endpoint
(``llm_router_api.endpoints.builtin.masking``).

The real ``FastMasker`` plugin is replaced by a mock so the tests stay
deterministic and hermetic; the endpoint wiring (required‑arg validation,
payload contract, masker invocation) is exercised for real.
"""

from __future__ import annotations

import os
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from llm_router_api.endpoints.builtin import masking as masking_ep  # noqa: E402


@pytest.fixture
def ep():
    with mock.patch.object(masking_ep, "FastMasker") as masker_cls:
        instance = masker_cls.return_value
        instance.mask_text.return_value = ("masked text", {"ph": "secret"})
        endpoint = masking_ep.FastTextMasking()
    endpoint._fast_masker = instance
    return endpoint


class TestFastTextMaskingConstruction:
    def test_masker_created_with_default_rules(self, ep):
        # ``rules=None`` → the plugin loads its full default rule set
        ep._fast_masker.mask_text.assert_not_called()

    def test_registration(self, ep):
        assert ep.name == "fast_text_mask"
        assert ep.method == "POST"
        assert ep._ep_types_str == ["builtin"]
        assert ep._dont_add_api_prefix is False
        assert ep.direct_return is True

    def test_required_args(self, ep):
        assert ep.REQUIRED_ARGS == ["text"]
        assert ep.OPTIONAL_ARGS is None
        assert ep.EP_DONT_NEED_GUARDRAIL_AND_MASKING is True


class TestFastTextMaskingPayload:
    def test_masks_text_and_returns_mappings(self, ep):
        out = ep.prepare_payload({"text": "raw sensitive text"})
        ep._fast_masker.mask_text.assert_called_once_with(text="raw sensitive text")
        assert out == {"text": "masked text", "mappings": {"ph": "secret"}}

    def test_extra_params_are_ignored_by_pydantic_model(self, ep):
        out = ep.prepare_payload({"text": "x", "unknown_key": 1})
        ep._fast_masker.mask_text.assert_called_once_with(text="x")
        assert out["text"] == "masked text"

    def test_non_string_text_rejected(self, ep):
        with pytest.raises(ValidationError):
            ep.prepare_payload({"text": 12345})

    def test_missing_text_raises_value_error(self, ep):
        with pytest.raises(ValueError, match="Missing required argument"):
            ep.prepare_payload({})

    def test_none_params_raise_value_error(self, ep):
        with pytest.raises(ValueError, match="Missing required argument"):
            ep.prepare_payload(None)
