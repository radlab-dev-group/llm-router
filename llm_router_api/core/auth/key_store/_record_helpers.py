"""
Shared helpers for API key record construction across all KeyStore backends.

All KeyStore implementations (Memory, Redis, Vault) use the same
key-prefix algorithm and default field values — this module centralizes them.
"""

from __future__ import annotations

import uuid
import hashlib

from typing import Any, Dict


def gen_key_prefix(key_plain: str) -> str:
    """
    Return the first 7 characters of *key_plain*, or the whole string if shorter.
    """

    return key_plain[:7] if len(key_plain) > 6 else key_plain


def gen_sha256_index(key_plain: str) -> str:
    """
    Return a deterministic O(1) index key: the hex SHA-256 of the plaintext key.

    All key stores keep a ``sha256(plaintext) -> key_id`` index so that a
    lookup finds the single candidate record in O(1) instead of scanning
    every stored key.  The candidate is then verified with ``bcrypt.checkpw``
    (constant-time) — the SHA-256 index is only a *locator*, never a proof of
    authenticity, so it is safe to store alongside the bcrypt hash.
    """

    return hashlib.sha256(key_plain.encode("utf-8")).hexdigest()


def gen_default_key_id() -> str:
    """
    Generate a default key ID with ``key-`` prefix.
    """

    return f"key-{uuid.uuid4().hex[:8]}"


# Default values for fields that are identical across all backends.
DEFAULT_RECORD_FIELDS = {
    "policy_name": "developer",
    "last_used_at": None,
    "is_active": True,
    "rotate_at": None,
}


def build_key_record(raw: dict) -> Dict:
    """
    Normalize a raw key record into the standard ApiKeyRecord shape.

    Fills defaults from :data:`DEFAULT_RECORD_FIELDS` where keys are missing,
    and ensures required interface fields are present. Plaintext is *never*
    included — only available at creation time.
    """
    record = dict(raw)  # avoid mutating caller
    for field, default in DEFAULT_RECORD_FIELDS.items():
        if field not in record:
            record[field] = default
    record.setdefault("key_hash", None)
    record.setdefault("key_plain", None)
    record.setdefault("metadata", {})
    record.setdefault("policy_override", None)
    return record


def apply_rate_limit_override(
    record: Dict[str, Any],
    rate_limit: Any,
) -> Dict[str, Any]:
    """
    Return a copy of *record* with the ``rate_limit`` policy override
    set (or cleared when *rate_limit* is ``None``).

    Other ``policy_override`` fields are preserved.  When clearing leaves
    the override empty, it is normalised to ``None``.
    """
    record = dict(record)
    override = dict(record.get("policy_override") or {})
    if rate_limit is None:
        override.pop("rate_limit", None)
        record["policy_override"] = override or None
    else:
        override["rate_limit"] = int(rate_limit)
        record["policy_override"] = override
    return record
