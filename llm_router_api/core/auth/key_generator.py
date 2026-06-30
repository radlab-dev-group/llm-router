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

        Parameters
        ----------
        entropy_bytes : int
            Number of cryptographically random bytes to use.  Defaults to
            48 (384 bits of entropy).

        Returns
        -------
        str
            A key like ``sk-litm-abc123XYZ...`` (48+ base62 chars after the prefix).
        """
        random_bytes = secrets.token_bytes(entropy_bytes)
        # Convert to base62 characters
        characters = [cls.CHARSET[b % len(cls.CHARSET)] for b in random_bytes]
        base62 = "".join(characters)

        return f"{cls.PREFIX}{base62}"

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
        return self.PREFIX
