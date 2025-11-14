"""
Rule that anonymizes Polish bank account numbers (IBAN format).

Polish IBAN example (full, un‑masked):
    PL56 1234 5678 9012 3456 7890 1234

The rule also recognises **partially masked** accounts where any group of
digits may be replaced with the literal string ``X`` (or a mixture of ``X``
and digits).  Example of a masked account that must be detected:

    XX 34 5678 9012 3456 1234 5678 9

In addition, the rule accepts the numeric part **without the country code**
(e.g. ``22 34 5678 9012 3456 1234 5678 9``).  Whitespace between groups
(spaces, tabs or new‑lines) is tolerated.  The placeholder used for
anonymisation is ``{{BANK_ACCOUNT}}``.
"""

import re
from typing import Match

from llm_router_lib.anonymizer.rules.base_rule import BaseRule


class BankAccountRule(BaseRule):
    """
    Detects Polish IBAN numbers, allowing optional masking with the literal
    ``X`` characters and also allowing the IBAN to be written without the
    leading country code (as sometimes seen in informal texts).
    """

    # Country code – either two uppercase letters (e.g. PL) or a masked ``XX``.
    # This part is optional because some texts omit it.
    _CC = r"(?:[A-Z]{2}|XX)?"

    # Two check digits – either two digits or a masked ``XX``.
    # Also optional for the same reason as the country code.
    _CHECK = r"(?:\d{2}|XX)?"

    # One group of the account number.  In a normal IBAN it is 4 digits,
    # but we also accept:
    #   * 1‑4 digits (the last group may be shorter)
    #   * a masked group consisting of X's (e.g. XXXX or XX)
    #   * a mixed mask like X1X2 (any combination of digits and X)
    _GROUP = r"(?:[0-9X]{1,4})"

    # The full pattern:
    #   optional country code, optional check digits, followed by
    #   5‑8 groups of 1‑4 characters (digits / X).  This covers:
    #     • the normal 6 groups of 4 digits (28 characters total)
    #     • partially masked forms where some groups are replaced by Xs
    #     • the short form without the country code (e.g. "22 34 …")
    _FULL_PATTERN = rf"""
        \b                      # word boundary – start of the IBAN
        {_CC}                   # optional country code (or masked)
        \s*                     # optional whitespace
        {_CHECK}                # optional check digits (or masked)
        (?:\s+{_GROUP}){{5,8}} # 5‑8 groups of 1‑4 chars (digits / X)
        \b                      # word boundary – end of the IBAN
    """

    _REGEX = _FULL_PATTERN

    _PLACEHOLDER = "{{BANK_ACCOUNT}}"

    def __init__(self):
        super().__init__(
            regex=self._REGEX,
            placeholder=self._PLACEHOLDER,
            flags=re.IGNORECASE | re.VERBOSE,
        )
        # Compile once for performance.
        self._compiled_regex = re.compile(
            self._REGEX, flags=re.IGNORECASE | re.VERBOSE
        )

    def apply(self, text: str) -> str:
        """
        Replace each detected (possibly masked) bank account number with the
        ``{{BANK_ACCOUNT}}`` placeholder.
        """

        def _replacer(match: Match) -> str:
            # No further validation is performed – the regex already ensures a
            # plausible Polish IBAN or a masked variant.
            return self._PLACEHOLDER

        return self._compiled_regex.sub(_replacer, text)
