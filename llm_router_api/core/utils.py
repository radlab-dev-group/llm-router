from typing import Optional, Any


class StrategyHelpers:
    @staticmethod
    def decode_redis(value: Any) -> Optional[str]:
        """
        Convert a Redis return value (bytes/bytearray/None) to a UTF‑8 string
        or ``None`` if the value is missing.
        """
        if value is None:
            return None
        if isinstance(value, (bytes, bytearray)):
            return value.decode("utf-8", errors="ignore")
        return str(value)

    @staticmethod
    def normalize_model_name(name: Optional[str]) -> str:
        """
        Return a canonical representation of a model name:

        * strips ``model:`` and ``host:`` prefixes,
        * trims surrounding whitespace,
        * guarantees a plain string (empty string if *name* is falsy).
        """
        if not name:
            return ""
        s = str(name).strip()
        if s.startswith("model:"):
            s = s[len("model:") :]
        if s.startswith("host:"):
            s = s[len("host:") :]
        return s.strip()

    @staticmethod
    def host_from_provider(provider) -> Optional[str]:
        """
        Extract the host identifier from a provider configuration.
        """
        return provider.get("api_host") or provider.get("host")
