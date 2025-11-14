"""
Rule that detects street names in Polish text.

Typical forms that are recognised (case‑insensitive, diacritics supported):

    ul. Mickiewicza 12
    ulica Marszałkowska 1A/2
    aleja Jana Pawła II 5
    plac Grunwaldzki 1
    przy Skwerze 3

The placeholder used for anonymisation is ``{{STREET}}``.
"""

import re
from typing import Match

from llm_router_lib.anonymizer.rules.base_rule import BaseRule


class StreetNameRule(BaseRule):
    """
    Detects Polish street names, allowing optional house numbers and common
    abbreviations.
    """

    # Common street type prefixes (full word or abbreviation)
    _TYPE = r"""
        (?:ul\.?|ulica|al\.?|aleja|pl\.?|plac|skwer|przy|przyjazna|
            os\.?|osiedle|rondo|droga|dr\.?|trakt|t\.?|ścieżka|ś\.?)
    """

    # Street name – one or more words, each may contain Polish diacritics
    _NAME = r"""
        (?:\s+[A-Za-zĄąĆćĘęŁłŃńÓóŚśŹźŻż][A-Za-z0-9ĄąĆćĘęŁłŃńÓóŚśŹźŻż-]*)+
    """

    # Optional house number (e.g. 12, 12A, 12/3)
    _NUMBER = r"""
        (?:\s*\d+[A-Za-z]?(?:\/\d+)? )?
    """

    # Full pattern with word boundaries on both sides
    _FULL_PATTERN = rf"""
        \b                      # start of word
        {_TYPE}                 # street type
        {_NAME}                 # street name
        {_NUMBER}               # optional house number
        \b                      # end of word
    """

    _REGEX = _FULL_PATTERN
    _PLACEHOLDER = "{{STREET}}"

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
        Replace each detected street name (with optional house number) with the
        ``{{STREET}}`` placeholder.
        """

        def _replacer(match: Match) -> str:
            return self._PLACEHOLDER

        return self._compiled_regex.sub(_replacer, text)
