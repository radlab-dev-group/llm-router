"""
hvac (optional Vault client) availability test.

Skipped when ``hvac`` is not installed (it is an optional dependency:
``pip install llm-router[vault]``).
"""

from __future__ import annotations

import importlib.util

import pytest

has_hvac = importlib.util.find_spec("hvac") is not None

pytestmark = pytest.mark.skipif(
    not has_hvac, reason="hvac (optional Vault client) is not installed"
)


def test_hvac_importable_and_factory_available() -> None:
    import hvac  # noqa: F401

    import llm_router_api.core.auth.key_store as ks

    assert ks._VAULT_AVAILABLE is True
    # The store module must bind the hvac Client API surface.
    import llm_router_api.core.auth.key_store.vault as vault_mod

    assert hasattr(vault_mod.VaultKeyStore, "_authenticate_vault")
