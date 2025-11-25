"""
Rule that masks EU VAT numbers.
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule
from llm_router_plugins.maskers.fast_masker.utils.validators import is_valid_eu_vat


class EuVatRule(BaseRule):
    """
    Detects EU VAT identifiers (e.g. ``PL1234567890``) and masks them with
    ``{{EU_VAT}}`` after a light format check.
    """

    _EU_VAT_REGEX = r"""
        \b
        [A-Z]{2}[A-Z0-9]{8,12}\b
    """

    def __init__(self):
        super().__init__(
            regex=self._EU_VAT_REGEX,
            placeholder="{{EU_VAT}}",
            flags=re.IGNORECASE | re.VERBOSE,
        )

    def apply(self, text: str) -> str:
        def _replace(m: re.Match) -> str:
            return self.placeholder if is_valid_eu_vat(m.group(0)) else m.group(0)

        return re.sub(self.pattern, _replace, text)
