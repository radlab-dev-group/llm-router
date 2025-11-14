"""
Utility validators for the anonymizer library.
"""


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
