"""
Rule that masks Polish health‑insurance identifiers (NFZ).
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule


class HealthIdRule(BaseRule):
    """
    Detects typical NFZ identifiers – 11 digits (optionally with a slash).
    Example: ``12345678901`` or ``12345678/901``.
    """

    # Only match the format with slash to avoid collision with PESEL
    _HEALTH_ID_REGEX = r"""
        \b
        \d{8}/\d{3}\b
    """

    def __init__(self):
        super().__init__(
            regex=self._HEALTH_ID_REGEX,
            placeholder="{{HEALTH_CODE}}",
            flags=re.VERBOSE,
        )
