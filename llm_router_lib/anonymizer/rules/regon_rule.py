"""
Rule that anonymizes Polish REGON numbers.

REGON (Rejestr Gospodarki Narodowej) may consist of:

* 9 digits – basic identifier for a legal entity
* 14 digits – identifier for a unit of a legal entity

Both forms contain a checksum digit.  The rule:

1. Detects a 9‑ or 14‑digit sequence (digits may be separated by a single
   space, which is common in documents, e.g. ``12345 6789`` or
   ``12345 6789 12345``).
2. Validates the checksum according to the official algorithm.
3. Replaces only **valid** REGON numbers with the placeholder ``{{REGON}}``.

The implementation follows the same pattern as the other anonymisation
rules in the project (inherits from ``BaseRule`` and pre‑compiles the
regular expression for speed).
"""

import re
from typing import Match

from llm_router_lib.anonymizer.rules.base_rule import BaseRule
from llm_router_lib.anonymizer.utils.validators import is_valid_regon


class RegonRule(BaseRule):
    """
    Detects Polish REGON numbers (9 or 14 digits, optional single spaces
    between groups) and replaces **valid** ones with ``{{REGON}}``.
    """

    # Regex that accepts:
    #   - 9 digits optionally split as 2‑3‑4 (e.g. 12 345 6789)
    #   - 14 digits optionally split as 2‑3‑4‑5 (e.g. 12 345 6789 12345)
    # The pattern captures the whole match (including spaces) in a named
    # group ``reg`` – later we strip the spaces before validation.
    _REGEX = r"""
        \b
        (?P<reg>
            (?:\d{2}\s?\d{3}\s?\d{4})          # 9‑digit block
            (?:\s?\d{5})?                      # optional 5‑digit block → 14‑digit form
        )
        \b
    """

    _PLACEHOLDER = "{{REGON}}"

    def __init__(self):
        super().__init__(
            regex=self._REGEX,
            placeholder=self._PLACEHOLDER,
            flags=re.IGNORECASE | re.VERBOSE,
        )
        # Compile once for fast reuse in ``apply``.
        self._compiled_regex = re.compile(
            self._REGEX, flags=re.IGNORECASE | re.VERBOSE
        )

    def apply(self, text: str) -> str:
        """
        Replace each *valid* REGON occurrence with the placeholder.
        Invalid numbers are left untouched.
        """

        def _replacer(match: Match) -> str:
            raw_regon = match.group("reg")
            return self._PLACEHOLDER if is_valid_regon(raw_regon) else raw_regon

        return self._compiled_regex.sub(_replacer, text)
