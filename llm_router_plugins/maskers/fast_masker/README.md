## Overview

The **fast_masker** plugin provides a simple, rule‑based engine that scans a piece of text and replaces sensitive data (
e‑mail addresses, IPs, URLs, phone numbers, Polish PESEL identifiers, etc.) with clearly marked placeholders.  
The core component is the :class:`~llm_router_plugins.plugins.fast_masker.core.masker.FastMasker`, which receives an
ordered list
of rule objects and applies each rule sequentially to the input text. Because the rules are applied in the order they
are supplied, you can control precedence (e.g., replace URLs before e‑mails if needed).

---

## Masking Rules

Rules are applied in order from **highest certainty** (checksum-validated) to **lowest certainty** (pattern-based). This ordering minimizes false positives and ensures the most reliable identifiers are masked first.

### 1. Highest Certainty — Checksum Validated Identifiers

| Rule                    | Placeholder          | What it Detects                                                                                          | Notes                                                                                   |
|-------------------------|----------------------|----------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| **CreditCardRule**      | `{{CREDIT_CARD}}`    | Credit card numbers (13-19 digits with optional spaces/dashes, e.g., `4532 1234 5678 9010`).            | Validates using Luhn algorithm checksum.                                                |
| **VinRule**             | `{{VIN}}`            | Vehicle Identification Numbers (17 characters, e.g., `1HGBH41JXMN109186`).                              | Validates using ISO 3779 checksum (position 9).                                         |
| **PeselTaggedRule**     | `{{PESEL_TAGGED}}`   | Polish PESEL with label (e.g., `PESEL: 44051401359`).                                                   | Validates checksum, preserves label prefix.                                             |
| **PeselRule**           | `{{PESEL}}`          | Polish PESEL numbers (11-digit personal identifiers).                                                    | Validates checksum via `is_valid_pesel`.                                                |
| **NipRule**             | `{{NIP}}`            | Polish NIP numbers (plain, hyphen-separated, or wrapped in markdown).                                   | Validates checksum with weights `[6,5,7,2,3,4,5,6,7]`.                                  |
| **KrsRule**             | `{{KRS}}`            | Polish KRS numbers (10 digits, plain or hyphen-separated).                                               | Validates checksum with weights `[2,3,4,5,6,7,8,9,2]`.                                  |
| **RegonRule**           | `{{REGON}}`          | Polish REGON numbers (9 or 14 digits, optionally split by spaces).                                      | Validates checksum; handles both 9-digit and 14-digit forms.                            |

### 2. High Certainty — Strict Format Validation

| Rule                    | Placeholder          | What it Detects                                                                                          | Notes                                                                                   |
|-------------------------|----------------------|----------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| **NrbRule**             | `{{NRB}}`            | Polish NRB (bank account) numbers (26 digits, optional spaces).                                          | Supports formats: `26 digits` or `2-4-4-4-4-4-4` grouping.                              |
| **MacAddressRule**      | `{{MAC_ADDRESS}}`    | MAC addresses (6 octets, e.g., `00:1A:2B:3C:4D:5E`).                                                     | Supports `:`, `-`, or no separators.                                                    |
| **PassportRule**        | `{{PASSPORT}}`       | Passport numbers (2 letters + 7 digits, e.g., `AB1234567`).                                             | Case-insensitive matching.                                                              |
| **IdCardRule**          | `{{ID_CARD}}`        | Polish ID card numbers (3 letters + 6 digits, e.g., `ABC123456`).                                       | Case-insensitive matching.                                                              |
| **SsnRule**             | `{{SSN}}`            | US Social Security Numbers (format `AAA-GG-SSSS`, e.g., `123-45-6789`).                                 | Format validation only, no checksum.                                                    |

### 3. Medium-High Certainty — International Phone Numbers

| Rule                         | Placeholder              | What it Detects                                                                                     | Notes                                                                                   |
|------------------------------|--------------------------|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| **PhoneInternationalRule**   | `{{PHONE_INTERNATIONAL}}`| Phone numbers with leading `+` and country code (e.g., `+48 123 456 789`).                          | Matches 1-3 digit country codes with subscriber number groups.                          |

### 4. Medium Certainty — Well-Structured Formats

| Rule                    | Placeholder          | What it Detects                                                                                          | Notes                                                                                   |
|-------------------------|----------------------|----------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| **EmailRule**           | `{{EMAIL}}`          | E-mail addresses (e.g., `user@example.com`).                                                             | Permissive regex; matches local-part, `@`, domain with TLD. Applied before URLs.        |
| **UrlRule**             | `{{URL}}`            | HTTP/HTTPS URLs and standalone domains (e.g., `https://example.com`, `www.wp.pl`).                      | Avoids code patterns like `requests.post`, `response.json`.                             |
| **IpRule**              | `{{IP}}`             | IPv4, IPv6 addresses and hostname `localhost`. Masks ports as `{{IP}}:{{PORT}}`.                         | Light octet validation; port captured separately.                                       |
| **BankAccountRule**     | `{{BANK_ACCOUNT}}`   | Polish IBAN (28 characters) and partially masked accounts (groups may contain `X`).                      | Exact length match; supports masked formats.                                            |

### 5. Medium-Low Certainty — Business Identifiers

| Rule                    | Placeholder              | What it Detects                                                                                      | Notes                                                                                   |
|-------------------------|--------------------------|------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| **JwtRule**             | `{{JWT}}`                | JSON Web Tokens (3 Base64URL parts separated by dots).                                              | Validates structure; each part must be substantial (≥20 chars for header/payload).      |
| **InvoiceNumberRule**   | `{{INVOICE_NUMBER}}`     | Invoice identifiers (e.g., `FV/2023/00123`, `INV-2023-456`).                                        | Case-insensitive; matches `FV`, `INV`, or `INVOICE` prefixes.                          |
| **OrderNumberRule**     | `{{ORDER_NUMBER}}`       | E-commerce order identifiers (e.g., `ORD123456`, `ORDER-2023-001`).                                 | Case-insensitive; matches `ORD` or `ORDER` prefixes.                                   |
| **TransactionRefRule**  | `{{TRANSACTION_REF}}`    | Transaction reference IDs (e.g., `TRX-20231125-001`).                                               | Matches 2-5 letter prefix, date/number pattern; validates length (8-64 chars).         |

### 6. Lower Certainty — Pattern-Based with Context

| Rule                    | Placeholder          | What it Detects                                                                                          | Notes                                                                                   |
|-------------------------|----------------------|----------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| **DateWordRule**        | `{{DATE_STR}}`       | Textual dates in Polish and English (e.g., `12 stycznia 2023`, `January 12, 2023`).                     | Supports month names, abbreviations, ordinal suffixes, commas.                          |
| **DateNumberRule**      | `{{DATE_NUM}}`       | Numeric dates (e.g., `YYYY.MM.DD`, `DD.MM.YYYY`).                                                       | Supports `-`, `/`, `.` separators with optional whitespace.                             |
| **MoneyRule**           | `{{MONEY}}`          | Monetary amounts with currency (symbols, ISO codes, or Polish words).                                   | Requires currency identifier; discards markdown emphasis.                               |

### 7. Format-Based — Specific Patterns

| Rule                    | Placeholder          | What it Detects                                                                                          | Notes                                                                                   |
|-------------------------|----------------------|----------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| **PostalCodeRule**      | `{{POSTAL_CODE}}`    | Polish postal codes (`dd-ddd` or `ddddd`), optionally wrapped in markdown.                              | Format-based only; no checksum validation.                                              |
| **HealthIdRule**        | `{{HEALTH_CODE}}`    | Polish NFZ health insurance IDs (format `ddddddd/ddd`, e.g., `12345678/901`).                           | Only matches slash format to avoid PESEL collision.                                     |
| **CarPlateRule**        | `{{CAR_PLATE}}`      | Polish vehicle plates (e.g., `ABC 12345`, `WA 1234A`).                                                  | Permissive validation; supports 2-3 letter prefix, 2-5 digits, optional suffix.        |
| **SimCardRule**         | `{{SIM_CARD}}`       | SIM card ICCID numbers (19-20 digits, optional spaces).                                                 | Length validation only.                                                                 |
| **SslCertRule**         | `{{SSL_CERT}}`       | SSL certificate serial numbers (16-40 hex characters).                                                  | Narrowed range to reduce false positives.                                               |

### 8. Lowest Certainty — Generic Patterns

| Rule                    | Placeholder          | What it Detects                                                                                          | Notes                                                                                   |
|-------------------------|----------------------|----------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| **PhoneRule**           | `{{PHONE}}`          | Polish phone numbers (9 digits, e.g., `123 456 789`, `123-456-789`).                                    | Supports `3-3-3` or `2-3-2-2` grouping with optional spaces/dashes.                     |
| **SocialIdRule**        | `{{SOCIAL_ID}}`      | Facebook numeric IDs (e.g., `fbid1234567890`).                                                           | Matches only `fbid` prefix (removed `@` to avoid email collision).                      |

### 9. Beta Features

| Rule                                | Placeholder        | What it Detects                                                                                       | Notes                                                                                   |
|-------------------------------------|--------------------|-------------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------|
| **StreetNameRule** *(beta)*         | `{{STREET}}`       | Polish street names with house numbers (e.g., `ul. Mickiewicza 12`, `aleja Jana Pawła II 5`).        | Recognizes common prefixes; limited to 1-5 words to prevent greedy matching.           |
| **SimplePersonalDataRule** *(beta)* | `{{MASKED}}`       | Polish surnames from CSV resources; matches whole words starting with uppercase.                      | Uses pre-loaded surname set with heuristic inflection handling.                         |

### Disabled Rules (Too Noisy)

The following rules are available in the codebase but **commented out** in the default configuration due to high false-positive rates:

- **EuVatRule** — EU VAT identifiers (catches words like "Configuration", "Architecture")
- **ApiKeyRule** — Generic API keys (too broad, requires 32+ chars with complexity check)
- **UserIdRule** — Generic user IDs (too broad, matches common numeric sequences)
- **ExtensionRule** — Phone extensions (too broad, matches common patterns)

Each rule implements the :class:`~llm_router_plugins.plugins.fast_masker.core.rule_interface.MaskerRuleI` interface,
exposing an `apply(text: str) -> str` method that returns the transformed string.

---

## Utility Validators

The plugin provides a comprehensive set of helper functions used by masking rules to verify the correctness of identified identifiers. All validators reside in `llm_router_plugins/maskers/fast_masker/utils/validators.py`.

### Polish Identification Numbers

- **`is_valid_pesel(pesel: str) -> bool`** — Validates Polish PESEL numbers (11 digits) using checksum weights `[1,3,7,9,1,3,7,9,1,3]`.
- **`is_valid_nip(raw_nip: str) -> bool`** — Validates Polish NIP (Tax ID) numbers (10 digits) using checksum weights `[6,5,7,2,3,4,5,6,7]`. Strips hyphens and spaces.
- **`is_valid_krs(raw_krs: str) -> bool`** — Validates Polish KRS (Court Register) numbers (10 digits) using checksum weights `[2,3,4,5,6,7,8,9,2]`. Remainder 10 is invalid.
- **`is_valid_regon(raw_regon: str) -> bool`** — Validates Polish REGON numbers (9 or 14 digits) with checksums for both forms. Remainder 10 becomes 0.

### Financial Numbers

- **`is_valid_credit_card(number: str) -> bool`** — Validates credit card numbers (13-19 digits) using the Luhn algorithm. Supports spaces and dashes.
- **`is_valid_nrb(nrb: str) -> bool`** — Validates Polish NRB bank account numbers (exactly 26 digits, optional spaces).

### Vehicle and Transport

- **`is_valid_vin(vin: str) -> bool`** — Validates 17-character VINs using ISO 3779 checksum (position 9). Excludes letters I, O, Q.
- **`is_valid_car_plate(plate: str) -> bool`** — Permissive validation for Polish car plates (2-3 letters, 2-5 digits, optional suffix).

### International Identification

- **`is_valid_ssn(ssn: str) -> bool`** — Validates US Social Security Number format `AAA-GG-SSSS`. Format-only, no checksum.
- **`is_valid_eu_vat(vat: str) -> bool`** — Validates EU VAT identifiers (2 letters + 8-12 alphanumerics). Requires minimum 6 digits to reduce false positives.

### Network and Security

- **`is_valid_mac(mac: str) -> bool`** — Validates MAC addresses (6 octets, separators `:`, `-`, or none).
- **`is_possible_token(token: str, min_len: int = 32) -> bool`** — Heuristic validation for API keys. Requires minimum length (default 32) and at least 2 character types (upper, lower, digit, special).
- **`is_possible_jwt(jwt: str) -> bool`** — Validates JWT structure (3 Base64URL parts separated by dots). Header and payload must be ≥20 chars each.
- **`is_valid_sim_iccid(iccid: str) -> bool`** — Validates SIM card ICCID numbers (19 or 20 digits, optional spaces).
- **`is_valid_ssl_serial(serial: str) -> bool`** — Validates SSL certificate serial numbers (16-40 hex characters).

### Business Identifiers

- **`is_possible_transaction_ref(ref: str) -> bool`** — Validates transaction reference format. Length 8-64 characters, must contain digits.

All validators return `True` for valid values and `False` otherwise, allowing masking rules to replace only genuine identifiers and minimize false positives.

