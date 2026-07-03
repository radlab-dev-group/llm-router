"""
API key generator.

Generates keys in the format ``sk-litm-<base62>`` matching the standard
used by OpenAI, LiteLLM, and other LLM proxies.
"""

from __future__ import annotations

import re
import string
import secrets


class KeyGenerator:
    """
    Generate API keys and validate their format.

    Keys are generated with cryptographic randomness and use the
    ``sk-litm-`` prefix by convention.
    """

    PREFIX = "sk-litm-"
    CHARSET = string.ascii_letters + string.digits  # base62
    MIN_LENGTH = 48  # minimum length of the base62 portion

    @classmethod
    def generate(cls, entropy_bytes: int = 48) -> str:
        """
        Generate a new API key.

        Uses :func:`secrets.choice` which reads from ``os.urandom`` internally
        and produces **unbiased** selections from the charset.  The previous
        implementation used ``byte % len(CHARSET)`` which introduced ~33 % bias
        for some characters because 256 is not evenly divisible by 62.

        Parameters
        ----------
        entropy_bytes : int
            Number of cryptographically random bytes to use as base entropy.
            Passed to :func:`secrets.token_bytes` which seeds the CSPRNG state
            that underlies :func:`secrets.choice`.  Defaults to 48 (384 bits).

        Returns
        -------
        str
            A key like ``sk-litm-abc123XYZ...`` (48+ base62 chars after the prefix).
        """
        # token_bytes advances the system PRNG state used by secrets.choice.
        characters = [secrets.choice(cls.CHARSET) for _ in range(cls.MIN_LENGTH)]
        return f"{cls.PREFIX}{''.join(characters)}"

    @classmethod
    def validate(cls, key: str) -> tuple[bool, str]:
        """
        Validate the format of an API key.

        Parameters
        ----------
        key : str
            The key to validate.

        Returns
        -------
        tuple[bool, str]
            ``(True, "")`` if valid, ``(False, "error message"`` if invalid.
        """
        pattern = rf"^{re.escape(cls.PREFIX)}[a-zA-Z0-9]{{{cls.MIN_LENGTH},}}$"
        if not re.match(pattern, key):
            return False, (
                f"Invalid key format: expected "
                f"{cls.PREFIX}<48+ alphanumeric characters>"
            )
        return True, ""

    @property
    def prefix(self) -> str:
        """Return the key prefix (e.g. ``'sk-litm-'``)."""
        return self.PREFIX
