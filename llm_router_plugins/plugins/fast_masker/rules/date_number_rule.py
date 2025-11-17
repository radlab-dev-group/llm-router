import re

from llm_router_plugins.plugins.fast_masker.rules.base_rule import BaseRule


class DateNumberRule(BaseRule):
    """
    Detects dates in the following numeric forms (separator may be ``.``, ``-``,
    ``/`` or whitespace‑wrapped variants):

    * ``YYYY.MM.DD``   – year‑month‑day
    * ``DD.MM.YYYY``   – day‑month‑year

    Whitespace may appear accidentally around the separators, e.g.
    ``2023 . 04 . 05`` or ``05 - 04 - 2023``.  All matches are replaced with
    ``{{DATE}}``.
    """

    # Regex with two alternatives:
    #   1) YYYY‑MM‑DD
    #   2) DD‑MM‑YYYY
    # Separators: dot, dash, slash, optionally surrounded by whitespace.
    REGEX = (
        r"(?<!\d)"  # not preceded by a digit
        r"(?:"
        # 1) YYYY‑MM‑DD
        r"(?P<year>\d{4})\s*[-./]\s*"
        r"(?P<month>0[1-9]|1[0-2])\s*[-./]\s*"
        r"(?P<day>0[1-9]|[12]\d|3[01])"
        r"|"
        # 2) DD‑MM‑YYYY
        r"(?P<day2>0[1-9]|[12]\d|3[01])\s*[-./]\s*"
        r"(?P<month2>0[1-9]|1[0-2])\s*[-./]\s*"
        r"(?P<year2>\d{4})"
        r")"
        r"(?!\d)"  # not followed by a digit
    )

    _MASKING_TAG_PLACEHOLDER = "{{DATE_NUM}}"

    _DATE_REGEX = re.compile(REGEX)

    def __init__(self):
        super().__init__(
            regex=DateNumberRule.REGEX,
            placeholder=DateNumberRule._MASKING_TAG_PLACEHOLDER,
        )

    def apply(self, text: str) -> str:
        """
        Replace every detected date (any of the supported formats) with the
        placeholder.
        """
        return self._DATE_REGEX.sub(self._MASKING_TAG_PLACEHOLDER, text)
