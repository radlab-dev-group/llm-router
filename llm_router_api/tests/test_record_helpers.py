"""
Unit tests for ``llm_router_api.core.auth.key_store._record_helpers``.

Covers the pure helper functions: key prefix generation, SHA-256 index,
default key id generation, record building and rate-limit override
application.  No external services required.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import re  # noqa: E402

from llm_router_api.core.auth.key_store._record_helpers import (  # noqa: E402
    DEFAULT_RECORD_FIELDS,
    apply_rate_limit_override,
    build_key_record,
    gen_default_key_id,
    gen_key_prefix,
    gen_sha256_index,
)


class TestGenKeyPrefix:
    def test_short_key_returned_as_is(self):
        assert gen_key_prefix("sk-123") == "sk-123"

    def test_long_key_truncated_to_12(self):
        key = "sk-llmr-live-abcdef123456"
        assert gen_key_prefix(key) == key[:12]
        assert len(gen_key_prefix(key)) == 12

    def test_default_prefix_fully_visible(self):
        # 12 chars covers the full default prefix "sk-llmr-live"
        assert gen_key_prefix("sk-llmr-live") == "sk-llmr-live"


class TestGenSha256Index:
    def test_deterministic(self):
        assert gen_sha256_index("sk-abc") == gen_sha256_index("sk-abc")

    def test_is_64_hex_chars(self):
        digest = gen_sha256_index("sk-abc")
        assert re.fullmatch(r"[0-9a-f]{64}", digest) is not None

    def test_different_keys_different_digests(self):
        assert gen_sha256_index("sk-1") != gen_sha256_index("sk-2")


class TestGenDefaultKeyId:
    def test_format(self):
        key_id = gen_default_key_id()
        assert key_id.startswith("key-")
        assert re.fullmatch(r"key-[0-9a-f]{8}", key_id) is not None

    def test_unique(self):
        assert gen_default_key_id() != gen_default_key_id()


class TestBuildKeyRecord:
    def test_defaults_filled(self):
        record = build_key_record({"key_id": "k1"})
        assert record["policy_name"] == "developer"
        assert record["last_used_at"] is None
        assert record["is_active"] is True
        assert record["rotate_at"] is None
        assert record["key_hash"] is None
        assert record["key_plain"] is None
        assert record["metadata"] == {}
        assert record["policy_override"] is None

    def test_explicit_values_preserved(self):
        raw = {
            "key_id": "k1",
            "policy_name": "pro",
            "is_active": False,
            "metadata": {"note": "x"},
            "policy_override": {"rate_limit": 10},
        }
        record = build_key_record(raw)
        assert record["policy_name"] == "pro"
        assert record["is_active"] is False
        assert record["metadata"] == {"note": "x"}
        assert record["policy_override"] == {"rate_limit": 10}

    def test_input_not_mutated(self):
        raw = {"key_id": "k1"}
        build_key_record(raw)
        assert raw == {"key_id": "k1"}

    def test_default_fields_constant(self):
        assert DEFAULT_RECORD_FIELDS["policy_name"] == "developer"
        assert DEFAULT_RECORD_FIELDS["is_active"] is True


class TestApplyRateLimitOverride:
    def test_set_rate_limit(self):
        record = apply_rate_limit_override({"key_id": "k1"}, 50)
        assert record["policy_override"] == {"rate_limit": 50}

    def test_rate_limit_coerced_to_int(self):
        record = apply_rate_limit_override({}, "100")
        assert record["policy_override"]["rate_limit"] == 100
        assert isinstance(record["policy_override"]["rate_limit"], int)

    def test_preserves_other_override_fields(self):
        base = {"policy_override": {"model_whitelist": ["m1"]}}
        record = apply_rate_limit_override(base, 5)
        assert record["policy_override"] == {
            "model_whitelist": ["m1"],
            "rate_limit": 5,
        }

    def test_none_clears_rate_limit(self):
        base = {"policy_override": {"rate_limit": 5}}
        record = apply_rate_limit_override(base, None)
        assert record["policy_override"] is None

    def test_none_preserves_other_fields(self):
        base = {"policy_override": {"rate_limit": 5, "model_whitelist": ["m"]}}
        record = apply_rate_limit_override(base, None)
        assert record["policy_override"] == {"model_whitelist": ["m"]}

    def test_input_not_mutated(self):
        base = {"policy_override": {"rate_limit": 5}}
        apply_rate_limit_override(base, 10)
        assert base == {"policy_override": {"rate_limit": 5}}
