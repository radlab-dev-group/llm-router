"""CLI command module for llm-router CLI."""

from .anonymizer import (
    _handle_anonymizer_from_args,
    main as anonymizer_main,
    register_anonymizer_subparser,
)
from .auth import register_auth_subparser, main as auth_main
from .config import main as config_main, register_config_subparser

__all__ = [
    "register_auth_subparser",
    "register_anonymizer_subparser",
    "register_config_subparser",
    "auth_main",
    "anonymizer_main",
    "config_main",
    "_handle_anonymizer_from_args",
]
