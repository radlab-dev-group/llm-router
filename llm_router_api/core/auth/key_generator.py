"""
API key generator.

Generates keys in the format ``sk-llmr-live-<base62>`` matching the standard
used by OpenAI, LiteLLM, and other LLM proxies.
"""

from __future__ import annotations

import re
import string
import secrets

from typing import Tuple


class KeyGenerator:
    """
    Generate API keys and validate their format.

    Keys are generated with cryptographic randomness and use the
    ``sk-llmr-live-`` prefix by convention.
    """

    PREFIX = "sk-llmr-live-"
    CHARSET = string.ascii_letters + string.digits  # base62
    MIN_LENGTH = 48  # minimum length of the base62 portion
    #: Default entropy asked for, in bytes (48 bytes = 384 bits).
    DEFAULT_ENTROPY_BYTES = 48
    #: Bits needed to encode one base62 character (ceil(log2(62))).
    BITS_PER_CHAR = 6

    @classmethod
    def generate(cls, entropy_bytes: int = DEFAULT_ENTROPY_BYTES) -> str:
        """
        Generate a new API key.

        Uses :func:`secrets.choice` which reads from ``os.urandom`` internally
        and produces **unbiased** selections from the charset.  The previous
        implementation used ``byte % len(CHARSET)`` which introduced ~33 % bias
        for some characters because 256 is not evenly divisible by 62.

        Parameters
        ----------
        entropy_bytes : int
            How much cryptographic entropy the key should carry, in bytes.  It
            sets the length of the base62 portion: one base62 character holds
            ``ceil(log2(62)) == 6`` bits, so *entropy_bytes* bytes need
            ``ceil(entropy_bytes * 8 / 6)`` characters.  The length never drops
            below :attr:`MIN_LENGTH`, so a smaller request cannot produce a
            weaker-than-minimum key.  Must be positive.

        Returns
        -------
        str
            A key like ``sk-llmr-live-abc123XYZ...``
            (at least :attr:`MIN_LENGTH` base62 chars after the prefix).

        Raises
        ------
        ValueError
            When *entropy_bytes* is not a positive number of bytes.
        """
        if entropy_bytes <= 0:
            raise ValueError("entropy_bytes must be a positive number of bytes")
        # ceil(entropy_bytes * 8 / BITS_PER_CHAR), without float arithmetic.
        needed = -(-(entropy_bytes * 8) // cls.BITS_PER_CHAR)
        length = max(cls.MIN_LENGTH, needed)
        characters = [secrets.choice(cls.CHARSET) for _ in range(length)]
        return f"{cls.PREFIX}{''.join(characters)}"

    @classmethod
    def validate(cls, key: str) -> Tuple[bool, str]:
        """
        Validate the format of an API key.

        Parameters
        ----------
        key : str
            The key to validate.

        Returns
        -------
        Tuple[bool, str]
            ``(True, "")`` if valid, ``(False, "error message"`` if invalid.
        """
        # ``re.fullmatch``, not ``re.match`` with ``$``: ``$`` also matches just
        # before a trailing newline, so ``"sk-llmr-live-aaa…\n"`` — a key with
        # whitespace smuggled in by a copy/paste or a header split — validated
        # as correct while never matching a stored hash.  fullmatch anchors at
        # the true end of the string.
        pattern = rf"{re.escape(cls.PREFIX)}[a-zA-Z0-9]{{{cls.MIN_LENGTH},}}"
        if not isinstance(key, str) or not re.fullmatch(pattern, key):
            return False, (
                f"Invalid key format: expected "
                f"{cls.PREFIX}<{cls.MIN_LENGTH}+ alphanumeric characters>"
            )
        return True, ""

    @property
    def prefix(self) -> str:
        """
        Return the key prefix (e.g. ``'sk-llmr-live-'``).
        """

        return self.PREFIX
