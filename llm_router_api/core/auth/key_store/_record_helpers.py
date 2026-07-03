"""Shared helpers for API key record construction across all KeyStore backends.

All KeyStore implementations (Memory, Redis, Vault) use the same
key-prefix algorithm and default field values — this module centralizes them.
"""

from __future__ import annotations

import uuid


def gen_key_prefix(key_plain: str) -> str:
    """Return the first 7 characters of *key_plain*, or the whole string if shorter."""
    return key_plain[:7] if len(key_plain) > 6 else key_plain


def gen_default_key_id() -> str:
    """Generate a default key ID with ``key-`` prefix."""
    return f"key-{uuid.uuid4().hex[:8]}"


# Default values for fields that are identical across all backends.
DEFAULT_RECORD_FIELDS = {
    "policy_name": "developer",
    "last_used_at": None,
    "is_active": True,
    "rotate_at": None,
}


def build_key_record(raw: dict) -> dict:
    """Normalize a raw key record into the standard ApiKeyRecord shape.

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
