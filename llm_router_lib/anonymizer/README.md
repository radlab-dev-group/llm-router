## Overview

The **anonymizer** library provides a simple, rule‑based engine that scans a piece of text and replaces sensitive data (
e‑mail addresses, IPs, URLs, phone numbers, Polish PESEL identifiers, etc.) with clearly marked placeholders.  
The core component is the :class:`~llm_router_lib.anonymizer.core.anonymizer.Anonymizer`, which receives an ordered list
of rule objects and applies each rule sequentially to the input text. Because the rules are applied in the order they
are supplied, you can control precedence (e.g., replace URLs before e‑mails if needed).

---

## Anonymization Rules

| Rule                      | Placeholder | What it Detects                                                                                                                                                          | Notes |
|---------------------------|-------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------|-------|
| **EmailRule**             | `{{EMAIL}}` | E‑mail addresses (`user@example.com`). Uses a permissive regex that matches the local‑part, the `@` symbol and a domain with a top‑level domain.                         |
| **IpRule**                | `{{IP}}`    | IPv4 (`192.168.0.1`) and IPv6 (`2001:0db8:85a3:0000:0000:8a2e:0370:7334`) addresses. The regex performs lightweight validation (octet ranges are not strictly enforced). |
| **UrlRule**               | `{{URL}}`   | HTTP/HTTPS URLs (`http://example.com`, `https://sub.domain.org/path?query`). The pattern captures the scheme, domain and optional path/query.                            |
| **PhoneRule**             | `{{PHONE}}` | Various phone number formats, including optional country codes, area codes, separators (`+48 123 456 789`, `123-456-789`, `(123) 456 7890`, `1234567890`).               |
| **PeselRule**             | `{{PESEL}}` | Polish PESEL numbers (11‑digit personal identifiers). Only replaces numbers that pass the checksum validation implemented in the utils validator.                        |
| **BaseRule** *(abstract)* | —           | Provides common behaviour for rules that only need a compiled regular expression and a placeholder. Concrete rules inherit from this class.                              |

Each rule implements the :class:`~llm_router_lib.anonymizer.core.rule_interface.AnonymizeRuleI` interface, exposing an
`apply(text: str) -> str` method that returns the transformed string.

---

## Utility Validators

The library ships a small set of helper functions used by the rules:

* **`is_valid_pesel(pesel: str) -> bool`**  
  Validates a Polish PESEL number by applying the official checksum algorithm (weights
  `[1, 3, 7, 9, 1, 3, 7, 9, 1, 3]`). Returns `True` only when the checksum matches; otherwise `False`. This validator is
  used by :class:`~llm_router_lib.anonymizer.rules.pesel_rule.PeselRule` to ensure that only genuine PESEL identifiers
  are anonymized.

Additional validators can be added to `anonymizer/utils/validators.py` as needed.

---

## Quick ways to run the script

### 1. Using a file (the safest)

``` shell
python run_anonymizer.py examples/input.txt -o examples/output.txt
```

*If you omit `-o …` the result will be printed on the console.*

### 2. Piping data (no interactive EOF needed)

``` shell
cat examples/input.txt | python run_anonymizer.py > anonymized.txt
# or
echo "My phone is +48 123 456 789" | python run_anonymizer.py
```

### 3. Interactive mode (manual typing)

``` shell
python run_anonymizer.py
```

Now type (or paste) your text, **then press**:

* **Linux/macOS:** `Ctrl‑D`
* **Windows:** `Ctrl‑Z` followed by `Enter`

The script will finish and display the anonymized output.
