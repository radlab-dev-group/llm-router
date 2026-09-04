"""
Small helpers for parsing JSON answers returned by LLMs.

Models frequently wrap a JSON payload in a markdown code fence
(`` ```json ... ``` ``).  The helpers here strip such a fence (only when the
text really starts with one) and parse the result, so both GenAI apps share
a single, predictable implementation.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = ["strip_code_fence", "loads_json"]


def strip_code_fence(text: str) -> str:
    """
    Remove a surrounding markdown code fence from *text* (if present).

    Handles the common ```` ```json ```` / ```` ``` ```` opening fence and a
    trailing ```` ``` ````.  Text without a leading fence is returned
    unchanged.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return text
    body = stripped[3:]
    if body.startswith("json"):
        body = body[4:]
    if body.endswith("```"):
        body = body[:-3]
    return body.strip()


def loads_json(text: str) -> Any:
    """
    Parse *text* as JSON, tolerating a surrounding code fence.

    Raises
    ------
    json.JSONDecodeError
        If the (cleaned) text is not valid JSON.
    """
    return json.loads(strip_code_fence(text))
