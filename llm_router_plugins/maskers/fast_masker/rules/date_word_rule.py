import re

from llm_router_plugins.maskers.fast_masker.rules.base_rule import BaseRule


class DateWordRule(BaseRule):
    """
    Detects dates written in words (Polish & English) and replaces them with
    ``{{DATE}}``.  The rule handles the most common textual representations,
    including:

    * Polish – ``DD miesiąc YYYY`` or ``YYYY miesiąc DD`` (genitive month
      forms and common abbreviations).
    * English – ``Month DD, YYYY`` or ``DD Month YYYY`` (full names,
      three‑letter abbreviations, optional ordinal suffixes and commas).

    Whitespace may appear arbitrarily around the components.
    """

    # ----- month name alternatives (Polish & English) -----------------------
    _PL_MONTHS = (
        "styczeń|stycznia|sty|"
        "luty|lutego|lut|"
        "marzec|marca|mar|"
        "kwiecień|kwietnia|kwi|"
        "maj|maja|"
        "czerwiec|czerwca|cze|"
        "lipiec|lipca|lip|"
        "sierpień|sierpnia|sie|"
        "wrzesień|września|wrz|"
        "październik|października|paź|"
        "listopad|listopada|lis|"
        "grudzień|grudnia|gru"
    )
    _EN_MONTHS = (
        "January|Jan|February|Feb|March|Mar|April|Apr|May|June|Jun|July|Jul|"
        "August|Aug|September|Sep|October|Oct|November|Nov|December|Dec"
    )

    # ----- regex ----------------------------------------------------------------
    # Two main alternatives: Polish and English.  Each side supports both
    # “day‑month‑year” and “year‑month‑day” order.
    REGEX = (
        r"(?<!\w)"  # left boundary
        r"(?:"
        # ---------- Polish ----------------------------------------------------
        r"(?:"  # 1a) DD month YYYY
        r"(?P<pl_day>\d{1,2})\s+"
        r"(?P<pl_month>" + _PL_MONTHS + r")\s+"
        r"(?P<pl_year>\d{4})"
        r")|(?:"
        r"(?P<pl_year2>\d{4})\s+"
        r"(?P<pl_month2>" + _PL_MONTHS + r")\s+"
        r"(?P<pl_day2>\d{1,2})"
        r")"
        r"|"
        # ---------- English ---------------------------------------------------
        r"(?:"  # 2a) Month DD, YYYY
        r"(?P<en_month>" + _EN_MONTHS + r")\s+"
        r"(?P<en_day>\d{1,2})(?:st|nd|rd|th)?"
        r"(?:,\s*|\s+)"  # optional comma
        r"(?P<en_year>\d{4})"
        r")|(?:"
        r"(?P<en_day2>\d{1,2})(?:st|nd|rd|th)?\s+"
        r"(?P<en_month2>" + _EN_MONTHS + r")\s+"
        r"(?P<en_year2>\d{4})"
        r")"
        r")"
        r"(?!\w)"  # right boundary
    )

    _PLACEHOLDER = "{{DATE_STR}}"

    _COMPILED = re.compile(REGEX, flags=re.IGNORECASE | re.VERBOSE)

    def __init__(self):
        super().__init__(
            regex=DateWordRule.REGEX,
            placeholder=DateWordRule._PLACEHOLDER,
        )

    def apply(self, text: str) -> str:
        """
        Replace any recognised textual date with the placeholder.
        """
        return self._COMPILED.sub(self._PLACEHOLDER, text)
