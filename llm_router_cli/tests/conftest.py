"""
Shared fixtures for the llm-router CLI tests.

Redirects the auth seed files (memory key store + rate-limit policies) to a
per-test temporary directory so tests never touch ``~/.llm-router``.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def auth_home(tmp_path, monkeypatch):
    """
    Redirect the auth CLI seed files into *tmp_path* and yield the seed file.

    Also isolates the rate-limit preset discovery (user config path) so the
    builtin presets are used deterministically.
    """
    import llm_router_api.base.const_global as cg

    # CLI import path — set before any llm_router_api config validation.
    cg.IS_CLI_COMMAND = True

    seed_file = str(tmp_path / "configs" / "auth" / "memory-keys.json")

    from llm_router_cli.cli.commands.auth import AuthCommand
    from llm_router_api.base import constants

    monkeypatch.setattr(AuthCommand, "SEED_DIR", tmp_path)
    monkeypatch.setattr(AuthCommand, "DEFAULT_SEED_FILE", seed_file)
    monkeypatch.setattr(constants, "LLM_ROUTER_AUTH_MEMORY_SEED_FILE", seed_file)
    return seed_file
