"""
Rule that masks credit‑card numbers.
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule
from llm_router_plugins.maskers.fast_masker.utils.validators import (
    is_valid_credit_card,
)


class CreditCardRule(BaseRule):
    """
    Detects 16‑digit credit‑card numbers (optionally separated by spaces or dashes)
    and replaces them with ``{{CREDIT_CARD}}`` **only if the Luhn checksum passes**.
    """

    # Regex captures the raw number; validation is performed in ``apply``.
    # Match 13-19 digits with optional spaces or dashes between groups
    _CC_REGEX = r"""
        \b
        \d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,7}   # Standard grouping: 4-4-4-(1-7)
        \b
    """

    def __init__(self):
        super().__init__(
            regex=self._CC_REGEX,
            placeholder="{{CREDIT_CARD}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )

    def apply(self, text: str) -> str:
        """Replace only syntactically valid credit‑card numbers."""

        def _replace(match: re.Match) -> str:
            candidate = match.group(0)
            return self.placeholder if is_valid_credit_card(candidate) else candidate

        return re.sub(self.pattern, _replace, text)
