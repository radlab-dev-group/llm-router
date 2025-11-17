"""
Rule that masks valid Polish PESEL numbers.
"""

import re

from llm_router_plugins.plugins.fast_masker.rules.base_rule import BaseRule
from llm_router_plugins.plugins.fast_masker.utils.validators import is_valid_pesel


class PeselRule(BaseRule):
    """
    Detects 11‑digit PESEL numbers, validates the checksum and replaces only
    the valid ones with ``{{PESEL}}``.
    """

    REGEX = r"(?<!\w)(?:[_*]+)?(?P<pesel>\d{11})(?:[_*]+)?(?!\w)"

    _MASK_TAG_PLACEHOLDER = "{{PESEL}}"

    _PESEL_REGEX = re.compile(REGEX)

    def __init__(self):
        super().__init__(
            regex=PeselRule.REGEX,
            placeholder=PeselRule._MASK_TAG_PLACEHOLDER,
        )

    def apply(self, text: str) -> str:
        """
        Replace each *valid* PESEL occurrence with the placeholder.

        Invalid PESEL strings (wrong checksum) are left untouched.
        """

        def replacer(match: re.Match) -> str:

            pesel = match.group("pesel")
            return self._MASK_TAG_PLACEHOLDER if is_valid_pesel(pesel) else pesel

        return self._PESEL_REGEX.sub(replacer, text)
