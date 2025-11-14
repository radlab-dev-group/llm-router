"""
Rule that anonymizes monetary amounts **only when a currency identifier is present**.
Supported currency indicators:

* Symbolic: $, €, £, ¥, ₽, ₹
* ISO‑code prefix/suffix: USD, EUR, GBP, PLN, … (case‑insensitive)
* Polish textual forms (case‑insensitive, optional trailing dot):
  zł, zł., złoty, złote, złotych, złotymi,
  dolar, dolara, dolarów, dolary, dolarami,
  euro, eur., eura, eurów, eurem,
  funt, funty, funtów, funtami,
  rubel, rubla, rubli, rublami

The rule recognises a wide variety of numeric formats (spaces, commas,
dots or non‑breaking spaces as thousand separators, optional decimal part)
and optional markdown emphasis markers (`_` or `*`).  Any matched amount is
replaced with the placeholder ``{{MONEY}}``.
"""

import re
from typing import Match

from llm_router_lib.anonymizer.rules.base_rule import BaseRule


class MoneyRule(BaseRule):
    """
    Detects monetary amounts that contain at least one currency identifier
    (prefix **or** suffix) together with a number.  The whole expression may be
    wrapped in markdown emphasis characters.
    """

    # --------------------------------------------------------------
    # Currency identifiers
    # --------------------------------------------------------------
    _CURRENCY_SYMBOLS = r"""[$€£¥₽₹]"""
    _CURRENCY_CODES = (
        r"""(?:USD|EUR|GBP|PLN|CHF|CAD|AUD|JPY|NOK|SEK|DKK|CZK|HUF|RUB|CNY|INR)"""
    )

    # Polish textual forms (case‑insensitive, optional trailing dot)
    _CURRENCY_WORDS = r"""(?i:
        (?:zł|zł\.|złoty|złote|złotych|złotymi|
           dolar|dolara|dolarów|dolary|dolarami|
           euro|eur\.|eura|eurów|eurem|
           funt|funty|funtów|funtami|
           rubel|rubla|rubli|rublami)
    )"""

    # --------------------------------------------------------------
    # Magnitude words that appear before/after the currency
    # --------------------------------------------------------------
    _MAGNITUDE_WORDS = r"""(?i:
        (?:tys\.|mln|mld)      # thousand, million, billion (Polish abbreviations)
    )"""

    # --------------------------------------------------------------
    # Numeric part (supports space, comma, dot or NBSP as thousands separator)
    # --------------------------------------------------------------
    _NUMBER = r"""
        \d{1,3}                     # first 1‑3 digits
        (?:[ ,.\u00A0]\d{3})*       # optional groups of separator + 3 digits
        (?:[.,]\d{1,2})?           # optional decimal part (dot or comma + 1‑2 digits)
    """

    # --------------------------------------------------------------
    # Full regex – two alternatives:
    #   1) currency prefix + number [+ optional magnitude + optional suffix]
    #   2) number + optional magnitude + currency suffix
    # Both alternatives may be surrounded by optional markdown markers.
    # --------------------------------------------------------------
    _MONEY_REGEX = rf"""
        (?<!\w)                                 # not part of a longer word/number
        (?:[_*]+)?                              # optional leading markdown markers
        (?:
            # ---- 1) prefix present ---------------------------------
            (?P<prefix>{_CURRENCY_SYMBOLS}|{_CURRENCY_CODES})   # prefix before amount
            \s*?
            (?P<amount1>{_NUMBER})                             # numeric amount
            (?:\s*(?P<magnitude1>{_MAGNITUDE_WORDS}))?        # optional magnitude
            (?:\s*
                (?P<suffix1>{_CURRENCY_SYMBOLS}|{_CURRENCY_CODES}|{_CURRENCY_WORDS})
            )?                                                  # optional suffix
        |
            # ---- 2) suffix (with optional magnitude) -------------
            (?P<amount2>{_NUMBER})                             # numeric amount
            (?:\s*(?P<magnitude2>{_MAGNITUDE_WORDS}))?        # optional magnitude
            \s*
            (?P<suffix2>{_CURRENCY_SYMBOLS}|{_CURRENCY_CODES}|{_CURRENCY_WORDS})
        )
        (?:[_*]+)?                              # optional trailing markdown markers
        (?!\w)                                 # not part of a longer word/number
    """

    _PLACEHOLDER = "{{MONEY}}"

    def __init__(self):
        super().__init__(
            regex=self._MONEY_REGEX,
            placeholder=self._PLACEHOLDER,
            flags=re.IGNORECASE | re.VERBOSE,
        )
        # Compile once for performance.
        self._compiled_regex = re.compile(
            self._MONEY_REGEX, flags=re.IGNORECASE | re.VERBOSE
        )

    def apply(self, text: str) -> str:
        """
        Replace each detected monetary amount (with a currency identifier) with
        ``{{MONEY}}``.  Markdown emphasis markers are discarded – the placeholder
        stands alone.
        """

        def _replacer(match: Match) -> str:
            # The regex guarantees that a currency identifier is present, so we
            # can safely replace the whole match with the placeholder.
            return self._PLACEHOLDER

        return self._compiled_regex.sub(_replacer, text)
