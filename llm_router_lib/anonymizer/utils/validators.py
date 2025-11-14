"""
Utility validators for the anonymizer library.
"""

import re


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
