# Python
"""
Rule that anonymizes Polish surnames.

The surnames are stored in two CSV files:
`resources/anonymizer/pl_surnames_male.csv` and
`resources/anonymizer/pl_surnames_female.csv`.

All surnames are loaded once (at import time) into a ``set`` of
lower‑cased strings, giving O(1) lookup per token.
The rule matches *any* word token (``\b\w+\b``) and replaces it with the
placeholder only when the token is present in the surname set.
"""

import csv
import re
from pathlib import Path
from typing import Set

from llm_router_lib.anonymizer.rules.base_rule import BaseRule


# ----------------------------------------------------------------------
# Load surnames once – this is shared by all instances of the rule.
# ----------------------------------------------------------------------
def _load_surnames() -> Set[str]:
    """
    Read the two CSV files containing male and female Polish surnames and
    return a set with all surnames in lower‑case.

    Returns
    -------
    Set[str]
        All surnames from both files.
    """
    base_dir = Path(__file__).resolve().parents[3] / "resources" / "anonymizer"
    csv_files = ["pl_surnames_male.csv", "pl_surnames_female.csv"]
    surnames: Set[str] = set()

    for file_name in csv_files:
        file_path = base_dir / file_name
        with file_path.open(newline="", encoding="utf-8") as f:
            for row in csv.reader(f):
                if row:
                    surname = row[0].strip()
                    if surname:
                        surnames.add(surname.lower())
    return surnames


_SURNAME_SET = _load_surnames()


# ----------------------------------------------------------------------
# Rule implementation
# ----------------------------------------------------------------------
class SimpleSurnameRule(BaseRule):
    """
    Detects Polish surnames and replaces them with ``{{SURNAME}}``.

    The detection is case‑insensitive and works on word boundaries.
    """

    # Match any word token; the actual replacement logic decides whether it
    # is a surname.
    _WORD_REGEX = r"\b\w+\b"

    def __init__(self):
        super().__init__(
            regex=self._WORD_REGEX,
            placeholder="{{SURNAME_SIMPLE}}",
            flags=re.IGNORECASE,
        )
        # Compile the regex once for the ``apply`` method.
        self._compiled_regex = re.compile(self._WORD_REGEX, flags=re.IGNORECASE)

    def apply(self, text: str) -> str:
        """
        Replace each surname found in *text* with ``{{SURNAME}}``.

        Parameters
        ----------
        text : str
            Input text to be anonymized.

        Returns
        -------
        str
            Text with surnames replaced by the placeholder.
        """

        def _replacer(match: re.Match) -> str:
            token = match.group(0)
            # ``_SURNAME_SET`` stores lower‑cased surnames → case‑insensitive check
            if token.lower() in _SURNAME_SET:
                return self.placeholder
            return token

        return self._compiled_regex.sub(_replacer, text)
