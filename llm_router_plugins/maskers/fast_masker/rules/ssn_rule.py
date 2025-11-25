"""
Rule that masks US Social Security Numbers.
"""

import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule
from llm_router_plugins.maskers.fast_masker.utils.validators import is_valid_ssn


class SsnRule(BaseRule):
    """
    Detects SSN patterns ``AAA‑GG‑SSSS`` and masks them with ``{{SSN}}``.
    """

    _SSN_REGEX = r"""
        \b
        \d{3}-\d{2}-\d{4}\b
    """

    def __init__(self):
        super().__init__(
            regex=self._SSN_REGEX,
            placeholder="{{SSN}}",
            flags=re.VERBOSE,
        )

    def apply(self, text: str) -> str:
        def _replace(m: re.Match) -> str:
            return self.placeholder if is_valid_ssn(m.group(0)) else m.group(0)

        return re.sub(self.pattern, _replace, text)
