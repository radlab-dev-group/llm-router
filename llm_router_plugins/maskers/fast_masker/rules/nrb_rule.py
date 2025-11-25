"""
Rule that masks Polish NRB (bank account) numbers.
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule
from llm_router_plugins.maskers.fast_masker.utils.validators import is_valid_nrb


class NrbRule(BaseRule):
    """
    Detects Polish NRB numbers (26 digits, optional spaces) and masks them with
    ``{{NRB}}`` after verifying length/format.
    """

    _NRB_REGEX = r"""
        \b
        (?:\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4})   # 2-4-4-4-4-4-4 or 26 digits
        |
        (?:\d{26})   # or 26 digits without spaces
        \b
    """

    def __init__(self):
        super().__init__(
            regex=self._NRB_REGEX,
            placeholder="{{NRB}}",
            flags=re.VERBOSE,
        )

    def apply(self, text: str) -> str:
        def _replace(m: re.Match) -> str:
            return self.placeholder if is_valid_nrb(m.group(0)) else m.group(0)

        return re.sub(self.pattern, _replace, text)
