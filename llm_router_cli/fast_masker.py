"""
Anonymisation command‑line interface.

This module provides a small command‑line utility that reads text from a
file (or standard input), applies a configurable set of anonymisation
rules, and writes the processed text to a file (or standard output).  The
available rules cover phone numbers, URLs, IP addresses, PESEL identifiers,
and e‑mail addresses.  Each rule can be disabled via a dedicated command‑line
flag.

Typical usage involves invoking the script with optional ``--disable-``
flags to omit specific transformations.  The utility streams the input and
output using UTF‑8 encoding and decorates the anonymised content with a
separator line for visual clarity.

---

# Quick ways to run the script

1. Using a file (the safest)

>>> python run_anonymizer.py examples/input.txt -o examples/output.txt

*If you omit `-o …` the result will be printed on the console.*


2. Piping data (no interactive EOF needed)

>>> cat examples/input.txt | python run_anonymizer.py > anonymized.txt

or

>>> echo "My phone is +48 123 456 789" | python run_anonymizer.py


3. Interactive mode (manual typing)

>>> python run_anonymizer.py

Now type (or paste) your text, **then press**:

* **Linux/macOS:** `Ctrl‑D`
* **Windows:** `Ctrl‑Z` followed by `Enter`

The script will finish and display the anonymised output.
"""

import argparse
import sys

from llm_router_plugins.plugins.fast_masker.core.masker import FastMasker
from llm_router_plugins.plugins.fast_masker.core.masker import (
    PhoneRule,
    UrlRule,
    IpRule,
    PeselRule,
    EmailRule,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Anonymize text using a configurable set of rules."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=argparse.FileType("r", encoding="utf-8"),
        default=sys.stdin,
        help="Input file (defaults to STDIN).",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=argparse.FileType("w", encoding="utf-8"),
        default=sys.stdout,
        help="Output file (defaults to STDOUT).",
    )
    parser.add_argument(
        "--disable-phone",
        action="store_true",
        help="Do not apply phone‑number anonymisation.",
    )
    parser.add_argument(
        "--disable-url", action="store_true", help="Do not apply URL anonymisation."
    )
    parser.add_argument(
        "--disable-ip",
        action="store_true",
        help="Do not apply IP‑address anonymisation.",
    )
    parser.add_argument(
        "--disable-pesel",
        action="store_true",
        help="Do not apply PESEL anonymisation.",
    )
    parser.add_argument(
        "--disable-email",
        action="store_true",
        help="Do not apply e-mail anonymisation.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Build the rule list respecting the disable flags
    rules = []

    if not args.disable_pesel:
        rules.append(PeselRule())

    if not args.disable_email:
        rules.append(EmailRule())

    if not args.disable_ip:
        rules.append(IpRule())

    if not args.disable_url:
        rules.append(UrlRule())

    if not args.disable_phone:
        rules.append(PhoneRule())

    anonymizer = FastMasker(rules)

    input_text = args.input.read()
    result = anonymizer.mask_text(input_text)
    args.output.write(result)


if __name__ == "__main__":
    main()
