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
