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
    Generate a richer set of heuristic inflected forms for Polish surnames.
    The approach distinguishes several common surname patterns and
    applies case‑specific suffixes for both masculine and feminine forms.

    The generated forms are **not** exhaustive linguistic models, but they
    cover the most frequent declension patterns used in everyday text,
    dramatically improving detection compared with the previous simple
    suffix list.
    """
    forms: Set[str] = set()
    b = base

    # ------------------------------------------------------------------
    # Helper: add a form if it looks plausible (non‑empty, alphabetic)
    # ------------------------------------------------------------------
    def _add(form: str) -> None:
        if form and form.isalpha():
            forms.add(form)

    # ------------------------------------------------------------------
    # 1. Very common masculine endings: -ski, -cki, -dzki, -owski, -ewski
    # ------------------------------------------------------------------
    masc_suffixes = ("ski", "cki", "dzki", "owski", "ewski")
    if any(b.endswith(suf) for suf in masc_suffixes):
        # Base masculine form (nominative)
        _add(b)

        # Feminine counterpart: replace trailing “i” with “a”
        fem = b[:-1] + "a"
        _add(fem)

        # Masculine case suffixes (genitive, dative, instrumental, locative)
        masc_cases = {
            "gen": "ego",  # Kowalskiego
            "dat": "emu",  # Kowalskiemu
            "inst": "im",  # Kowalskim
            "loc": "im",  # Kowalskim (locative often same as instrumental)
            "voc": "",  # vocative rarely changes for these surnames
            "pl": "owie",  # plural nominative (Kowalscy → Kowalscy, but we keep a simple form)
        }
        for case, suffix in masc_cases.items():
            _add(b[:-1] + suffix)  # drop trailing “i”, add case suffix
            _add(fem + suffix)  # same suffix for feminine when applicable

        # Feminine case suffixes
        fem_cases = {
            "gen": "iej",  # Kowalskiej
            "dat": "iej",  # Kowalskiej
            "acc": "ą",  # Kowalską
            "inst": "ą",  # Kowalską
            "loc": "iej",  # Kowalskiej
            "voc": "",  # unchanged
        }
        for case, suffix in fem_cases.items():
            _add(fem + suffix)

    # ------------------------------------------------------------------
    # 2. Surnames ending with -owicz / -ewicz (typical patronymics)
    # ------------------------------------------------------------------
    elif b.endswith("owicz") or b.endswith("ewicz"):
        _add(b)  # nominative
        _add(b + "a")  # genitive (e.g., Nowakowicza)
        _add(b + "owi")  # dative
        _add(b + "em")  # instrumental
        _add(b + "u")  # locative
        _add(b + "owie")  # plural

    # ------------------------------------------------------------------
    # 3. Surnames ending with -ak, -ek, -ik, -yk (common masculine forms)
    # ------------------------------------------------------------------
    elif any(b.endswith(suf) for suf in ("ak", "ek", "ik", "yk")):
        # Basic masculine declension
        _add(b)  # nom.
        _add(b + "a")  # gen.
        _add(b + "owi")  # dat.
        _add(b + "a")  # acc. (same as gen. for animate)
        _add(b + "iem")  # inst.
        _add(b + "u")  # loc.
        _add(b + "owie")  # plural

        # Feminine version (if surname already ends with -a)
        if b.endswith("a"):
            _add(b)  # nom.
            _add(b + "ej")  # gen./dat./loc.
            _add(b + "ą")  # acc./inst.

    # ------------------------------------------------------------------
    # 4. Fallback: attach a set of generic suffixes that catch most cases
    # ------------------------------------------------------------------
    else:
        generic_suffixes = [
            "a",
            "u",
            "owi",
            "em",
            "emu",
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
        for suf in generic_suffixes:
            _add(b + suf)

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
