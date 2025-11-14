"""
Rule that anonymizes valid Polish PESEL numbers.
"""

import re

from llm_router_lib.anonymizer.rules.base_rule import BaseRule
from llm_router_lib.anonymizer.utils.validators import is_valid_pesel


class PeselRule(BaseRule):
    """
    Detects 11‑digit PESEL numbers, validates the checksum and replaces only
    the valid ones with ``{{PESEL}}``.
    """

    REGEX = r"\b\d{11}\b"

    _ANONYMIZATION_TAG_PLACEHOLDER = "{{PESEL}}"

    _PESEL_REGEX = re.compile(REGEX)

    def __init__(self):
        super().__init__(
            regex=PeselRule.REGEX,
            placeholder=PeselRule._ANONYMIZATION_TAG_PLACEHOLDER,
        )

    def apply(self, text: str) -> str:
        """
        Replace each *valid* PESEL occurrence with the placeholder.

        Invalid PESEL strings (wrong checksum) are left untouched.
        """

        def replacer(match: re.Match) -> str:
            pesel = match.group(0)
            return (
                self._ANONYMIZATION_TAG_PLACEHOLDER
                if is_valid_pesel(pesel)
                else pesel
            )

        return self._PESEL_REGEX.sub(replacer, text)
