## Overview

The **fast_masker** plugin provides a simple, rule‑based engine that scans a piece of text and replaces sensitive data (
e‑mail addresses, IPs, URLs, phone numbers, Polish PESEL identifiers, etc.) with clearly marked placeholders.  
The core component is the :class:`~llm_router_plugins.plugins.fast_masker.core.masker.FastMasker`, which receives an
ordered list
of rule objects and applies each rule sequentially to the input text. Because the rules are applied in the order they
are supplied, you can control precedence (e.g., replace URLs before e‑mails if needed).

---

## Masking Rules

| Rule                                | Placeholder        | What it Detects                                                                                                                                   | Notes                                                                                             |
|-------------------------------------|--------------------|---------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| **EmailRule**                       | `{{EMAIL}}`        | E‑mail addresses (e.g., `user@example.com`).                                                                                                      | Uses a permissive regex that matches the local‑part, `@`, and a domain with a TLD.                |
| **IpRule**                          | `{{IP}}`           | IPv4, IPv6 addresses and the hostname `localhost`. Also masks ports as `{{IP}}:{{PORT}}` when a port follows the address.                         | Light validation of octet ranges; port is captured separately.                                    |
| **UrlRule**                         | `{{URL}}`          | HTTP/HTTPS URLs and plain domain names (e.g., `https://example.com`, `www.wp.pl`).                                                                | Optional scheme, optional path/query/fragment.                                                    |
| **PhoneRule**                       | `{{PHONE}}`        | Various phone number formats, with optional country/area codes and separators (`+48 123 456 789`, `123-456-789`, `(123) 456 7890`, `1234567890`). | Very permissive pattern.                                                                          |
| **PeselRule**                       | `{{PESEL}}`        | Polish PESEL numbers (11‑digit personal identifiers).                                                                                             | Validates checksum via `is_valid_pesel`.                                                          |
| **BankAccountRule**                 | `{{BANK_ACCOUNT}}` | Polish IBAN numbers (full 28‑character form) and partially masked accounts where any group may contain `X`.                                       | Matches exact length; no further validation required.                                             |
| **DateNumberRule**                  | `{{DATE_NUM}}`     | Numeric dates in forms `YYYY.MM.DD`, `DD.MM.YYYY` (also with `-`, `/` or whitespace separators).                                                  | Handles surrounding whitespace; replaces with `{{DATE_NUM}}`.                                     |
| **DateWordRule**                    | `{{DATE_STR}}`     | Textual dates in Polish and English (e.g., `12 stycznia 2023`, `January 12, 2023`).                                                               | Supports month names, abbreviations, optional ordinal suffixes and commas.                        |
| **KrsRule**                         | `{{KRS}}`          | Polish KRS numbers (plain or hyphen‑separated) that pass checksum validation.                                                                     | Uses `is_valid_krs` for verification.                                                             |
| **MoneyRule**                       | `{{MONEY}}`        | Monetary amounts that contain a currency identifier (symbols, ISO codes, or Polish words) together with a number.                                 | Discards surrounding markdown emphasis; replaces whole match.                                     |
| **NipRule**                         | `{{NIP}}`          | Polish NIP numbers (plain, hyphen‑separated, embedded in letters, or wrapped in markdown).                                                        | Validates checksum via `_is_valid_nip`.                                                           |
| **PostalCodeRule**                  | `{{POSTAL_CODE}}`  | Polish postal codes in forms `dd-ddd` or `ddddd`, optionally wrapped in markdown emphasis.                                                        | No checksum validation; format‑based detection only.                                              |
| **RegonRule**                       | `{{REGON}}`        | Polish REGON numbers (9 or 14 digits, optionally split by single spaces) that pass checksum validation.                                           | Uses `is_valid_regon` after stripping spaces.                                                     |
| **StreetNameRule** *(beta)*         | `{{STREET}}`       | Polish street names with optional house numbers (e.g., `ul. Mickiewicza 12`, `aleja Jana Pawła II`).                                              | Recognises common street type prefixes and abbreviations; case‑insensitive, diacritics supported. |
| **SimplePersonalDataRule** *(beta)* | `{{MASKED}}`       | Polish surnames loaded from CSV resources; matches whole words that start with an uppercase letter.                                               | Uses a pre‑loaded set of surnames with heuristic inflection handling.                             |
| **BaseRule** *(abstract)*           | —                  | Provides common behaviour for rules that only need a compiled regular expression and a placeholder.                                               | Concrete rules inherit from this class.                                                           |

Each rule implements the :class:`~llm_router_plugins.plugins.fast_masker.core.rule_interface.MaskerRuleI` interface,
exposing an `apply(text: str) -> str` method that returns the transformed string.

---

## Utility Validators

The plugin provides a set of helper functions used by several masking rules to
verify the correctness of identified identifiers:

- **`is_valid_pesel(pesel: str) -> bool`** – validates Polish PESEL numbers by
  checking length, date components and checksum.
- **`is_valid_krs(krs: str) -> bool`** – checks the KRS checksum for both plain
  and hyphen‑separated forms.
- **`is_valid_regon(regon: str) -> bool`** – validates 9‑ or 14‑digit REGON
  numbers, handling optional spaces and checksum calculation.
- **`_is_valid_nip(nip: str) -> bool`** – internal helper used by `NipRule`
  to verify the Polish NIP checksum.
- Additional internal helpers (e.g., `_load_surnames`, `_generate_inflected_forms`)
  support the beta rules but are not part of the public validator API.

These validators reside in
`llm_router_plugins/plugins/fast_masker/utils/validators.py` and are imported
by the corresponding rule implementations. They return `True` for valid values
and `False` otherwise, allowing the masking rules to replace only genuine
identifiers.

