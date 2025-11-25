"""
Utility validators for the masker plugin.
"""

import re
from typing import Iterable


# ============================================================================
# Polish identification numbers
# ============================================================================


def is_valid_pesel(pesel: str) -> bool:
    """
    Validate a Polish PESEL number.

    The algorithm:
    1. Multiply the first 10 digits by the weight vector
       [1, 3, 7, 9, 1, 3, 7, 9, 1, 3].
    2. Sum the results and take ``mod 10``.
    3. The checksum digit is ``(10 - sum_mod) % 10``.
    4. Compare the checksum digit with the 11th digit.

    Parameters
    ----------
    pesel: str
        A string consisting of exactly 11 digits.

    Returns
    -------
    bool
        ``True`` if the PESEL passes the checksum test, otherwise ``False``.
    """
    if not (pesel.isdigit() and len(pesel) == 11):
        return False

    weights = [1, 3, 7, 9, 1, 3, 7, 9, 1, 3]
    digits = [int(ch) for ch in pesel]

    checksum_calc = sum(w * d for w, d in zip(weights, digits[:10])) % 10
    checksum_expected = (10 - checksum_calc) % 10

    return checksum_expected == digits[10]


def is_valid_nip(raw_nip: str) -> bool:
    """
    Validate a Polish NIP (Tax Identification Number).

    The NIP consists of 10 digits.  The checksum is calculated with the
    weights ``[6, 5, 7, 2, 3, 4, 5, 6, 7]``; the sum of the weighted digits
    modulo 11 must equal the last digit.

    ``raw_nip`` may contain hyphens (e.g. ``123-456-78-90``) – they are stripped
    before validation.
    """
    # Remove any hyphens or spaces that may be present
    digits = re.sub(r"[-\s]", "", raw_nip)

    if not re.fullmatch(r"\d{10}", digits):
        return False

    weights = (6, 5, 7, 2, 3, 4, 5, 6, 7)
    checksum = sum(w * int(d) for w, d in zip(weights, digits[:9])) % 11
    return checksum == int(digits[9])


def is_valid_krs(raw_krs: str) -> bool:
    """
    Validate a Polish KRS (National Court Register) number.

    The KRS consists of 10 digits.  The checksum is calculated using the
    weights ``[2, 3, 4, 5, 6, 7, 8, 9, 2]`` applied to the first nine digits.
    The control digit (the 10‑th digit) is simply the **remainder of the weighted
    sum divided by 11**.  If the remainder equals 10 the number is considered
    invalid (the official specification does not define a replacement digit).

    ``raw_krs`` may contain hyphens or spaces (e.g. ``123-456-78-90``) – they
    are stripped before validation.
    """
    # Remove any hyphens or spaces that may be present
    digits = re.sub(r"[-\s]", "", raw_krs)

    if not re.fullmatch(r"\d{10}", digits):
        return False

    weights = (2, 3, 4, 5, 6, 7, 8, 9, 2)
    weighted_sum = sum(w * int(d) for w, d in zip(weights, digits[:9]))
    control_digit = weighted_sum % 11

    # A remainder of 10 is not a valid control digit
    if control_digit == 10:
        return False

    return control_digit == int(digits[9])


def is_valid_regon(raw_regon: str) -> bool:
    """
    Validate a Polish REGON number.

    * 9‑digit REGON – checksum weights: [8, 9, 2, 3, 4, 5, 6, 7]
    * 14‑digit REGON – first 9 digits are validated as above,
      then digits 1‑13 (including the 9‑digit checksum) are validated
      with weights: [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5, 6]

    The checksum is ``sum % 11``; if the result is 10 the checksum digit
    becomes 0.
    """
    # Remove any whitespace that may be present
    digits = re.sub(r"\s+", "", raw_regon)

    if not re.fullmatch(r"\d{9}|\d{14}", digits):
        return False

    def checksum(value: str, weights: list[int]) -> int:
        s = sum(int(d) * w for d, w in zip(value, weights))
        r = s % 11
        return 0 if r == 10 else r

    # ----- 9‑digit validation -----
    w9 = [8, 9, 2, 3, 4, 5, 6, 7]
    if len(digits) == 9:
        return checksum(digits[:8], w9) == int(digits[8])

    # ----- 14‑digit validation -----
    # first part (first 9 digits) must be correct
    if checksum(digits[:8], w9) != int(digits[8]):
        return False

    w14 = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5, 6]
    return checksum(digits[:13], w14) == int(digits[13])


# ============================================================================
# Financial numbers
# ============================================================================


def _luhn_checksum(number: str) -> int:
    """Calculate Luhn checksum for a numeric string."""
    digits = [int(d) for d in number[::-1]]
    total = 0
    for i, d in enumerate(digits):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10


def is_valid_credit_card(number: str) -> bool:
    """
    Validate a credit‑card number (13-19 digits, optional spaces or dashes)
    using the Luhn algorithm.
    """
    cleaned = re.sub(r"[ -]", "", number)
    if not cleaned.isdigit():
        return False
    if not (13 <= len(cleaned) <= 19):
        return False
    return _luhn_checksum(cleaned) == 0


def is_valid_nrb(nrb: str) -> bool:
    """Validate Polish NRB (26 digits, optional spaces)."""
    cleaned = re.sub(r"\s+", "", nrb)
    return cleaned.isdigit() and len(cleaned) == 26


# ============================================================================
# Vehicle and transport
# ============================================================================

_VIN_TRANSLATION = {
    **{c: i for i, c in enumerate("ABCDEFGHJKLMNPRSTUVWXYZ", start=1)},
    **{str(i): i for i in range(10)},
}
_VIN_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2]


def is_valid_vin(vin: str) -> bool:
    """Validate a 17‑character VIN using its checksum (position 9)."""
    vin = vin.upper()
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
        return False
    total = sum(_VIN_TRANSLATION[ch] * w for ch, w in zip(vin, _VIN_WEIGHTS))
    remainder = total % 11
    check = "X" if remainder == 10 else str(remainder)
    return vin[8] == check


def is_valid_car_plate(plate: str) -> bool:
    """Very permissive Polish car‑plate validation."""
    return bool(re.fullmatch(r"[A-Z]{2,3}\s?\d{2,5}[A-Z]{0,2}", plate.upper()))


# ============================================================================
# International identification
# ============================================================================


def is_valid_ssn(ssn: str) -> bool:
    """Validate SSN format ``AAA‑GG‑SSSS`` (no checksum)."""
    return bool(re.fullmatch(r"\d{3}-\d{2}-\d{4}", ssn))


def is_valid_eu_vat(vat: str) -> bool:
    """Validate EU VAT identifier (e.g. ``PL1234567890``)."""
    vat_upper = vat.upper()
    # Must be 2 letters + digits/letters (8-12 chars)
    if not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{8,12}", vat_upper):
        return False
    # Count digits - must have at least 6 digits to avoid matching regular words
    digit_count = sum(c.isdigit() for c in vat_upper[2:])
    return digit_count >= 6


# ============================================================================
# Network and security
# ============================================================================


def is_valid_mac(mac: str) -> bool:
    """Validate MAC address (e.g. ``00:1A:2B:3C:4D:5E``)."""
    return bool(re.fullmatch(r"(?:[0-9A-Fa-f]{2}[:\-]?){5}[0-9A-Fa-f]{2}", mac))


def is_possible_token(token: str, min_len: int = 32) -> bool:
    """
    Heuristic check for API keys: length + allowed characters + complexity.
    Accepts alphanumerics, ``-`` and ``_``.
    Requires at least 2 types of characters (upper, lower, digit, special).
    """
    if len(token) < min_len:
        return False

    if not re.fullmatch(r"[A-Za-z0-9\-_]+", token):
        return False

    # Must have mixed case or contain special chars
    has_upper = any(c.isupper() for c in token)
    has_lower = any(c.islower() for c in token)
    has_digit = any(c.isdigit() for c in token)
    has_special = any(c in "-_" for c in token)

    complexity = sum([has_upper, has_lower, has_digit, has_special])
    return complexity >= 2


def is_possible_jwt(jwt: str) -> bool:
    """Detect something that looks like a JWT."""
    parts = jwt.split(".")
    if len(parts) != 3:
        return False
    # Each part must be base64url and have reasonable length
    for i, p in enumerate(parts):
        if not p or not re.fullmatch(r"[A-Za-z0-9\-_]+", p):
            return False
        # Header and payload should be substantial
        if i < 2 and len(p) < 20:
            return False
    return True


def is_valid_sim_iccid(iccid: str) -> bool:
    """Validate SIM card ICCID (19 or 20 digits)."""
    cleaned = re.sub(r"\s+", "", iccid)
    return cleaned.isdigit() and 19 <= len(cleaned) <= 20


def is_valid_ssl_serial(serial: str) -> bool:
    """Validate SSL certificate serial (16-40 hex chars)."""
    return bool(re.fullmatch(r"[0-9A-Fa-f]{16,40}", serial))


# ============================================================================
# Business identifiers
# ============================================================================


def is_possible_transaction_ref(ref: str) -> bool:
    """Validate transaction reference format."""
    if not (8 <= len(ref) <= 64):
        return False
    # Must contain digits
    return bool(re.search(r"\d", ref))
