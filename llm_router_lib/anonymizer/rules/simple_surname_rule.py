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
            header = True
            for row in csv.reader(f):
                if header:
                    header = False
                    continue

                if row:
                    surname = row[0].strip()
                    count = int(row[1])

                    if count < 400:
                        continue

                    print(f"Adding {surname} with count {count}")
                    if surname:
                        base = surname.lower()
                        # forma podstawowa
                        surnames.add(base)
                        # wstrzyknięcie prostych, odmienionych form
                        surnames.update(_generate_inflected_forms(base))
    return surnames


def _generate_inflected_forms(base: str) -> Set[str]:
    """
    Generuje proste, heurystyczne formy odmienione nazwiska w oparciu o formę podstawową.

    Uwaga: to nie jest pełny model fleksji, tylko zestaw najczęstszych końcówek,
    żeby złapać typowe przypadki typu:
    - Nowak -> Nowaka, Nowakiem, Nowakowi, Nowaków, Nowakom, Nowakami, Nowaku, Nowakiem, Nowaku itd.
    - Kowalski -> Kowalskiego, Kowalskiemu, Kowalskim, Kowalskich, Kowalskimi, Kowalska, Kowalską, Kowalskiej, Kowalscy...
    """
    forms: Set[str] = set()
    b = base

    # Najczęstsze końcówki przypadków dla nazwisk w mianowniku męskim
    common_suffixes = [
        "a",
        "u",
        "owi",
        "iem",
        "iemu",
        "iem",
        "om",
        "ów",
        "ami",
        "ach",
        "y",
        "ie",
        "ą",
        "ę",
        "owie",
    ]
    for suf in common_suffixes:
        forms.add(b + suf)

    # Bardzo prosta obsługa nazwisk na -ski/-cki/-dzki (żeńskie odpowiedniki)
    if b.endswith("ski") or b.endswith("cki") or b.endswith("dzki"):
        # ski -> ska, cki -> cka, dzki -> dzka (obcięcie końcowego "i")
        fem = b[:-1] + "a"
        forms.add(fem)
        fem_suffixes = [
            "ą",
            "ie",
            "iej",
            "ą",
            "ę",
        ]  # Kowalską, Kowalskiej, Kowalską, Kowalskę
        for suf in fem_suffixes:
            forms.add(fem + suf)

    return forms


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
            if token.lower() in _SURNAME_SET:
                return self.placeholder
            return token

        return self._compiled_regex.sub(_replacer, text)
