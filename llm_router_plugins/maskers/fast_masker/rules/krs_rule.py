"""
Rule that masks valid Polish KRS numbers.
"""

import re
from typing import Match

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule
from llm_router_plugins.maskers.fast_masker.utils.validators import is_valid_krs


class KrsRule(BaseRule):
    """
    Detects KRS numbers (plain ``1234567890`` or formatted ``123-456-78-90``),
    validates the checksum and replaces **only** the valid ones with
    ``{{KRS}}``.
    """

    # Named group ``krs`` captures the whole match (including optional hyphens)
    _KRS_REGEX = r"""
        \b
        (?P<krs>
            (?:\d{3}-?\d{3}-?\d{2}-?\d{2})   # formatted with optional hyphens
            |
            \d{10}                           # plain 10‑digit string
        )
        \b
    """

    _PLACEHOLDER = "{{KRS}}"

    def __init__(self):
        super().__init__(
            regex=self._KRS_REGEX,
            placeholder=self._PLACEHOLDER,
            flags=re.IGNORECASE | re.VERBOSE,
        )
        # Pre‑compile the pattern for fast reuse in ``apply``.
        self._compiled_regex = re.compile(
            self._KRS_REGEX, flags=re.IGNORECASE | re.VERBOSE
        )

    def apply(self, text: str) -> str:
        """
        Replace each *valid* KRS occurrence with the placeholder.
        Invalid KRS strings (wrong checksum) are left untouched.
        """

        def _replacer(match: Match) -> str:
            raw_krs = match.group("krs")
            return self._PLACEHOLDER if is_valid_krs(raw_krs) else raw_krs

        return self._compiled_regex.sub(_replacer, text)
