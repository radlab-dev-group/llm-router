"""
Rule that anonymizes valid Polish NIP numbers.
"""

import re
from typing import Match

from llm_router_lib.anonymizer.rules.base_rule import BaseRule


def _is_valid_nip(raw_nip: str) -> bool:
    """
    Validate a Polish NIP (Tax Identification Number).

    The NIP consists of 10 digits.  The checksum is calculated with the
    weights ``[6, 5, 7, 2, 3, 4, 5, 6, 7]``; the sum of the weighted digits
    modulo 11 must equal the last digit.

    ``raw_nip`` may contain hyphens (e.g. ``123-456-78-90``) – they are stripped
    before validation.
    """
    # Remove hyphens and spaces
    digits = re.sub(r"[-\s]", "", raw_nip)

    if not re.fullmatch(r"\d{10}", digits):
        return False

    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    checksum = sum(w * int(d) for w, d in zip(weights, digits[:9])) % 11
    return checksum == int(digits[9])


class NipRule(BaseRule):
    """
    Detects NIP numbers in the following forms:

    * Plain 10‑digit string: ``1234567890``
    * Hyphen‑separated: ``123-456-78-90``
    * Embedded in letters: ``b1234567890b``
    * Wrapped with markdown emphasis: ``_b1234567890b*_``

    Only valid NIPs (correct checksum) are replaced with ``{{NIP}}``.
    """

    # The regex captures the digit part (with optional hyphens) in a named group
    # ``digits``.  It allows optional leading/trailing markdown markers (`_` or `*`)
    # and letters around the digits.
    _NIP_REGEX = r"""
        (?<!\d)                     # not preceded by another digit
        (?:[_*]+)?                  # optional leading markdown markers
        (?P<digits>
            (?:\d{3}-?\d{3}-?\d{2}-?\d{2})   # optional hyphens
            |
            \d{10}                           # plain 10‑digit string
        )
        (?:[_*]+)?                  # optional trailing markdown markers
        (?!\d)                      # not followed by another digit
    """

    _PLACEHOLDER = "{{NIP}}"

    def __init__(self):
        super().__init__(
            regex=self._NIP_REGEX,
            placeholder=self._PLACEHOLDER,
            flags=re.IGNORECASE | re.VERBOSE,
        )
        # Pre‑compile for performance
        self._compiled_regex = re.compile(
            self._NIP_REGEX, flags=re.IGNORECASE | re.VERBOSE
        )

    def apply(self, text: str) -> str:
        """
        Replace each *valid* NIP occurrence with the placeholder.
        Invalid NIPs are left unchanged.
        """

        def _replacer(match: Match) -> str:
            raw_nip = match.group("digits")
            return self._PLACEHOLDER if _is_valid_nip(raw_nip) else match.group(0)

        return self._compiled_regex.sub(_replacer, text)
