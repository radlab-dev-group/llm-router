"""Utility helpers for ``llm_router_lib``.

This subpackage currently provides:

* :class:`HttpRequester` — a thin wrapper around ``requests`` that adds logging,
  retries and unified error translation.
"""

from llm_router_lib.utils.http import HttpRequester

__all__ = [
    "HttpRequester",
]
