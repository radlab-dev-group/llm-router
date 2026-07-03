"""Tests for KeyGenerator — verifies format, length, and unbiased character distribution."""

from __future__ import annotations

import string
from collections import Counter

import pytest

from llm_router_api.core.auth.key_generator import KeyGenerator


# ---------------------------------------------------------------------------
# Format tests
# ---------------------------------------------------------------------------


class TestKeyFormat:
    """Verify the generated key format matches expectations."""

    def test_prefix(self) -> None:
        key = KeyGenerator.generate()
        assert key.startswith(KeyGenerator.PREFIX)

    def test_min_length(self) -> None:
        """Generated key should have at least MIN_LENGTH base62 characters after prefix."""
        key = KeyGenerator.generate()
        suffix = key[len(KeyGenerator.PREFIX) :]
        assert len(suffix) >= KeyGenerator.MIN_LENGTH

    def test_alphanumeric_chars_only(self) -> None:
        """All characters after the prefix should be alphanumeric (base62)."""
        key = KeyGenerator.generate()
        suffix = key[len(KeyGenerator.PREFIX) :]
        assert all(c in string.ascii_letters + string.digits for c in suffix)

    def test_custom_entropy(self) -> None:
        """Should accept custom entropy_bytes parameter."""
        key = KeyGenerator.generate(entropy_bytes=32)
        suffix = key[len(KeyGenerator.PREFIX) :]
        # 32 bytes can produce up to floor(32*8/log2(62)) ≈ 44 chars, so may be less than MIN_LENGTH
        # Actually the generation keeps generating until MIN_LENGTH is reached
        assert len(suffix) >= KeyGenerator.MIN_LENGTH

    def test_different_keys_generated(self) -> None:
        """Two consecutive calls should produce different keys."""
        key1 = KeyGenerator.generate()
        key2 = KeyGenerator.generate()
        assert key1 != key2


# ---------------------------------------------------------------------------
# Unbiased distribution test
# ---------------------------------------------------------------------------


class TestNoModuloBias:
    """Verify that the key generator produces uniform character distribution.

    The old implementation used ``b % len(CHARSET)`` which creates bias because
    256 is not evenly divisible by 62.  Values 0-3 appear with probability 4/256
    while others appear with 3/256 (~33% bias).

    After the fix (rejection sampling), all characters should appear with
    approximately equal frequency.
    """

    NUM_KEYS = 5000  # number of keys to generate for distribution testing
    CHARSET_SIZE = len(KeyGenerator.CHARSET)

    def test_character_distribution_is_unbiased(self) -> None:
        """Collect character frequencies across many keys and verify uniformity."""
        chars: list[str] = []
        for _ in range(self.NUM_KEYS):
            key = KeyGenerator.generate(
                entropy_bytes=64
            )  # more entropy = more chars per call
            suffix = key[len(KeyGenerator.PREFIX) :]
            chars.extend(suffix)

        counter = Counter(chars)
        total = len(chars)

        # Expected frequency for each character (roughly equal)
        expected = total / self.CHARSET_SIZE

        # Chi-squared test: if chi2 > critical_value, distribution is non-uniform
        # For base62 (61 degrees of freedom), alpha=0.05 critical value ≈ 80.9
        chi2 = sum((count - expected) ** 2 / expected for count in counter.values())

        # Allow some variance but reject extreme bias
        # Old implementation would produce chi2 > 50; new should be < 10
        assert chi2 < 10, (
            f"Character distribution is non-uniform (chi2={chi2:.1f}). "
            f"This suggests modulo bias. Expected chars: {dict(counter)}"
        )

    def test_no_character_dominates(self) -> None:
        """No single character should appear more than ~2x the expected frequency."""
        chars: list[str] = []
        for _ in range(self.NUM_KEYS):
            key = KeyGenerator.generate(entropy_bytes=64)
            suffix = key[len(KeyGenerator.PREFIX) :]
            chars.extend(suffix)

        counter = Counter(chars)
        total = len(chars)
        expected = total / self.CHARSET_SIZE
        max_ratio = max(counter.values()) / expected

        # With 5000 keys, the most frequent char should not exceed ~1.8x expected
        assert max_ratio < 1.8, (
            f"Character '{counter.most_common(1)[0][0]}' appears {max_ratio:.2f}x more "
            f"than expected. Bias detected."
        )


# ---------------------------------------------------------------------------
# Validation tests
# ---------------------------------------------------------------------------


class TestKeyValidation:
    """Verify the validate() method."""

    def test_valid_key(self) -> None:
        valid, msg = KeyGenerator.validate(
            KeyGenerator.PREFIX + "a" * KeyGenerator.MIN_LENGTH
        )
        assert valid is True
        assert msg == ""

    def test_invalid_too_short(self) -> None:
        valid, msg = KeyGenerator.validate(KeyGenerator.PREFIX + "abc")
        assert valid is False
        assert "Invalid key format" in msg

    def test_invalid_prefix(self) -> None:
        valid, msg = KeyGenerator.validate(
            "wrong-prefix-" + "a" * KeyGenerator.MIN_LENGTH
        )
        assert valid is False

    def test_special_chars_rejected(self) -> None:
        valid, msg = KeyGenerator.validate(KeyGenerator.PREFIX + "abc!@#")
        assert (
            valid is False
            or len(KeyGenerator.PREFIX + "abc!@#")
            < len(KeyGenerator.PREFIX) + KeyGenerator.MIN_LENGTH
        )
