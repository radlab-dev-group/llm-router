"""CLI command module for llm-router CLI."""

from .anonymizer import (
    _handle_anonymizer_from_args,
    main as anonymizer_main,
    register_anonymizer_subparser,
)
from .auth import register_auth_subparser, main as auth_main

__all__ = [
    "register_auth_subparser",
    "register_anonymizer_subparser",
    "auth_main",
    "anonymizer_main",
    "_handle_anonymizer_from_args",
]
