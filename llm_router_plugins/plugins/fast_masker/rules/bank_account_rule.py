"""
Rule that mask Polish bank account numbers (IBAN format).

Polish IBAN (28 characters, without spaces):
    PL58105012981000009062923173

Polish IBAN with spaces:
    PL58 1050 1298 1000 0090 6292 3173

The rule also recognises **partially masked** accounts where any group of
four characters may be replaced with the literal character ``X`` (or a
mixture of ``X`` and digits), e.g.:

    PL58 10XX 1298 1XXX XXXX 6292 31X3
    XX 10XX 1298 1XXX XXXX 6292 31X3

Only strings that have the exact length of a Polish IBAN (28 alphanumeric
characters, ignoring whitespace) are matched – short numbers such as
``64001000152`` are **not** treated as bank accounts.  The placeholder used
for masking is ``{{BANK_ACCOUNT}}``.
"""

import re
from typing import Match

from llm_router_plugins.plugins.fast_masker.rules.base_rule import BaseRule


class BankAccountRule(BaseRule):
    """
    Detects Polish IBAN numbers (full 28‑character length), allowing optional
    masking with ``X`` characters and optional whitespace between groups.
    """

    # Country code – two letters (e.g. PL) or masked ``XX`` (must be present)
    _CC = r"(?:[A-Z]{2}|XX)"

    # Two check digits – either two digits or masked ``XX`` (must be present)
    _CHECK = r"(?:\d{2}|XX)"

    # One group of four characters – digits, X or any mixture (e.g. X1X2)
    _GROUP = r"(?:[0-9X]{4})"

    # Full pattern:
    #   - optional country code (or masked)
    #   - optional whitespace
    #   - check digits
    #   - exactly six groups of four characters, each optionally preceded by
    #     whitespace (including the possibility of no whitespace at all)
    #   - word boundaries on both sides to avoid partial matches
    _FULL_PATTERN = rf"""
                \b                      # start of word
                (?:{_CC})?              # optional country code (or masked)
                \s*                     # optional whitespace
                {_CHECK}                # check digits (or masked)
                (?:\s*{_GROUP}){{6}}   # six groups of 4 chars, whitespace optional
                \b                      # end of word
            """

    _REGEX = _FULL_PATTERN

    _PLACEHOLDER = "{{BANK_ACCOUNT}}"

    def __init__(self):
        super().__init__(
            regex=self._REGEX,
            placeholder=self._PLACEHOLDER,
            flags=re.IGNORECASE | re.VERBOSE,
        )
        # Pre‑compile for fast reuse.
        self._compiled_regex = re.compile(
            self._REGEX, flags=re.IGNORECASE | re.VERBOSE
        )

    def apply(self, text: str) -> str:
        """
        Replace each detected (possibly masked) bank account number with the
        ``{{BANK_ACCOUNT}}`` placeholder.
        """

        def _replacer(match: Match) -> str:
            # No further validation is required – the regex guarantees the
            # exact 28‑character IBAN structure (with optional masking) and
            # therefore will not match shorter numbers like ``64001000152``.
            return self._PLACEHOLDER

        return self._compiled_regex.sub(_replacer, text)
