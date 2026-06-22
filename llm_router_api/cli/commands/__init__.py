"""
CLI command module for llm-router.
"""

from .auth import register_auth_subparser, main as main_auth

__all__ = ["register_auth_subparser", "main_auth"]
