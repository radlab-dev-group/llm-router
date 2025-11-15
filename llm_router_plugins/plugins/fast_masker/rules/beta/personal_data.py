"""
Rule that masking Polish surnames.

The surnames are stored in two CSV files:
`resources/masker/pl_surnames_male.csv` and
`resources/masker/pl_surnames_female.csv`.

All surnames are loaded once (at import time) into a ``set`` of
lower‑cased strings, giving O(1) lookup per token.
The rule matches *any* word token (``\b\w+\b``) and replaces it with the
placeholder only when the token is present in the surname set.
"""

import csv
import re
from pathlib import Path
from typing import Set

from llm_router_plugins.plugins.fast_masker.rules.base_rule import BaseRule


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
    base_dir = Path(__file__).resolve().parents[3] / "resources" / "masker"
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
                    if count < 150:
                        continue

                    # print(f" -> adding {surname} with count {count}")
                    if surname:
                        base = surname.lower()
                        surnames.add(base)
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

    # ----------------------------------------------------------------------
    # Helper: add a form if it looks plausible (non‑empty, alphabetic)
    # ----------------------------------------------------------------------
    def _add(form: str) -> None:
        if form and form.isalpha():
            forms.add(form)

    # ----------------------------------------------------------------------
    # 1. Very common masculine endings: -ski, -cki, -dzki, -owski, -ewski
    # ----------------------------------------------------------------------
    masc_suffixes = ("ski", "cki", "dzki", "owski", "ewski")
    if any(b.endswith(suf) for suf in masc_suffixes):
        _add(b)

        # Feminine counterpart: replace trailing “i” with “a”
        fem = b[:-1] + "a"
        _add(fem)

        # Masculine case suffixes (genitive, dative, instrumental, locative)
        # For these patterns the correct forms keep the trailing “i”
        # before the case ending.
        masc_cases = {
            "gen": "ego",
            "dat": "emu",
            "inst": "em",
            "loc": "em",
            "voc": "",
            "pl": "owie",
        }
        for case, suffix in masc_cases.items():
            _add(b + suffix)
            _add(fem + suffix)

        # Feminine case suffixes (these do NOT keep the “i”)
        fem_cases = {
            "gen": "iej",
            "dat": "iej",
            "acc": "ą",
            "inst": "ą",
            "loc": "iej",
            "voc": "",
        }
        for case, suffix in fem_cases.items():
            _add(fem + suffix)

    # ----------------------------------------------------------------------
    # 2. Surnames ending with -owicz / -ewicz (typical patronymics)
    # ----------------------------------------------------------------------
    elif b.endswith("owicz") or b.endswith("ewicz"):
        _add(b)  # nominative
        _add(b + "a")  # genitive
        _add(b + "owi")  # dative
        _add(b + "em")  # instrumental
        _add(b + "u")  # locative
        _add(b + "owie")  # plural

    # ----------------------------------------------------------------------
    # 3. Surnames ending with -ak, -ek, -ik, -yk (common masculine forms)
    # ----------------------------------------------------------------------
    elif any(b.endswith(suf) for suf in ("ak", "ek", "ik", "yk")):
        _add(b)  # nominative
        _add(b + "a")  # genitive
        _add(b + "owi")  # dative
        _add(b + "a")  # accusative
        _add(b + "iem")  # instrumental
        _add(b + "u")  # locative
        _add(b + "owie")  # plural

        # Feminine version (if surname already ends with -a)
        if b.endswith("a"):
            _add(b)  # nominative
            _add(b + "ej")  # genitive / dative / locative
            _add(b + "ą")  # accusative / instrumental

    # ----------------------------------------------------------------------
    # 4. Masculine surnames that end with -a
    # ----------------------------------------------------------------------
    elif b.endswith("a"):
        stem = b[:-1]
        _add(stem)
        _add(stem + "ą")
        _add(stem + "u")
        _add(stem + "ą")
        _add(stem + "e")
        _add(stem + "owie")

    # ----------------------------------------------------------------------
    # 5. Surnames ending with -ko
    # ----------------------------------------------------------------------
    if b.endswith("ko"):
        stem = b[:-2]
        _add(b)
        _add(stem + "ki")
        _add(stem + "ce")
        _add(stem + "ką")

    # ----------------------------------------------------------------------
    # 5. Surnames ending with -ec / -iec
    # ----------------------------------------------------------------------
    elif b.endswith("iec") or b.endswith("ec"):
        if b.endswith("iec"):
            stem = b[:-4]
        else:
            stem = b[:-3]
        stem += "ń"

        _add(b)
        _add(stem + "ca")
        _add(stem + "cowi")
        _add(stem + "cem")
        _add(stem + "ńcem")
        _add(stem + "cu")
        _add(stem + "cowie")

    # ----------------------------------------------------------------------
    # 6. Fallback: attach a set of generic suffixes that catch most cases
    # ----------------------------------------------------------------------
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


class SimplePersonalDataRule(BaseRule):
    # Match any word token;
    # The actual replacement logic decides whether it is a surname.
    _WORD_REGEX = r"\b\w+\b"

    def __init__(self):
        super().__init__(
            regex=self._WORD_REGEX,
            placeholder="{{MASKED}}",
            flags=re.IGNORECASE,
        )
        # Compile the regex at once for the ``apply`` method.
        self._compiled_regex = re.compile(self._WORD_REGEX, flags=re.IGNORECASE)

    def apply(self, text: str) -> str:
        """
        Replace each surname found in *text* with ``{{SURNAME_SIMPLE}}``.
        The rule now substitutes only when the token starts with an
        uppercase letter (e.g., ``Maj``) and leaves a lower‑case
        occurrence (e.g., ``maj``) untouched.
        """

        def _replacer(match: re.Match) -> str:
            token = match.group(0)
            lowered = token.lower()
            # Replace only if the token is
            #  - a known surname
            #  - *and* begins with an uppercase character.
            if lowered in _SURNAME_SET and token[:1].isupper() and len(token) > 2:
                return self.placeholder
            return token

        return self._compiled_regex.sub(_replacer, text)
