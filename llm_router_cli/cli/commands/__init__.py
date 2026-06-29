"""CLI command module for llm-router CLI."""

from .auth import register_auth_subparser, main as auth_main

__all__ = ["register_auth_subparser", "auth_main"]
