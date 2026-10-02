"""
Optional Google Cloud credentials handling for Vertex AI providers.

The module resolves a Google access token for providers that do not carry
an explicit ``api_token``.  Resolution order:

1. ``provider_options.credentials_file`` – path to a service‑account JSON
   file;
2. Google Application Default Credentials (``GOOGLE_APPLICATION_CREDENTIALS``
   environment variable, GCE/GKE metadata server, or Workload Identity
   federation) via ``google.auth.default``.

``google-auth`` is an **optional** dependency (``pip install
radlab-llm-router[google]``).  When it is missing,
:class:`GoogleAccessTokenProvider` raises a :class:`RuntimeError` with the
install hint instead of failing at import time, so the router keeps working
for every other provider type.
"""

from __future__ import annotations

import calendar
import datetime
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

try:  # optional dependency – see the module docstring
    from google.auth.transport.requests import (  # type: ignore[import-not-found]
        Request,
    )
except ImportError:  # pragma: no cover - exercised via mock in tests
    Request = None
    try:
        from google import auth as google_auth  # type: ignore[import-not-found]
    except ImportError:
        google_auth = None
else:
    from google import auth as google_auth

_GOOGLE_AUTH_AVAILABLE = google_auth is not None and Request is not None

#: Scope used for Vertex AI calls when the operator does not override it.
DEFAULT_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

#: Tokens are refreshed this many seconds before their expiry.
#: A malformed value must not break module import – fall back to the default.
try:
    TOKEN_REFRESH_SKEW_SECONDS = int(
        os.environ.get("LLM_ROUTER_GOOGLE_TOKEN_REFRESH_SKEW", 120)
    )
except (TypeError, ValueError):
    TOKEN_REFRESH_SKEW_SECONDS = 120

#: Fallback TTL (seconds) for credentials that report no expiry.
_FALLBACK_TTL_SECONDS = 3000


class GoogleAccessTokenProvider:
    """
    Resolve and cache Google access tokens for Vertex AI providers.

    The cache is process‑wide and keyed by the credentials source
    (service‑account file or ADC environment) and the requested scopes, so
    gunicorn workers each keep their own token without a shared store.
    """

    _LOCK = threading.Lock()
    _CACHE: Dict[str, Tuple[str, float]] = {}
    #: Per‑credential refresh locks.  They stop a burst of concurrent requests
    #: from minting one token each, without holding ``_LOCK`` across the network
    #: call.  Entries are never dropped: swapping the locks would let two threads
    #: refresh the same credential at once again.
    _REFRESH_LOCKS: Dict[str, threading.Lock] = {}

    @classmethod
    def clear_cache(cls) -> None:
        """
        Drop all cached tokens (used by tests and credential rotation).

        Only ``_CACHE`` is cleared — the per‑key refresh locks are deliberately
        kept, since discarding them would break the mutual exclusion of any
        refresh already in flight.
        """
        with cls._LOCK:
            cls._CACHE.clear()

    @classmethod
    def _refresh_lock(cls, key: str) -> threading.Lock:
        """Return (creating on demand) the refresh lock of one credential key."""
        with cls._LOCK:
            lock = cls._REFRESH_LOCKS.get(key)
            if lock is None:
                lock = threading.Lock()
                cls._REFRESH_LOCKS[key] = lock
            return lock

    @classmethod
    def invalidate(cls, provider_options: Optional[Dict[str, Any]] = None) -> None:
        """
        Forget the cached token of ``provider_options`` (used on a 401/403).

        Best‑effort: the next request — or the next monitor ping — mints a fresh
        token instead of replaying one the upstream already rejected.
        """
        key = cls._cache_key(dict(provider_options or {}))
        with cls._LOCK:
            dropped = cls._CACHE.pop(key, None)
        if dropped is not None:
            logger.debug(
                "Evicted rejected Google access token (source=%s)", key or "ADC"
            )

    @classmethod
    def _cached_token(cls, key: str) -> Optional[str]:
        """
        Return the cached token of ``key`` while it is outside the refresh skew.
        """
        with cls._LOCK:
            cached = cls._CACHE.get(key)
        if cached is None:
            return None
        token, expires_at = cached
        if time.time() < expires_at - TOKEN_REFRESH_SKEW_SECONDS:
            return token
        return None

    @staticmethod
    def _to_epoch(expiry: Any) -> Optional[float]:
        """
        Convert a credential expiry into a POSIX timestamp.

        ``google-auth`` exposes ``credentials.expiry`` as a **naive UTC**
        datetime (it is built from ``utcnow()``), while
        ``datetime.timestamp()`` reads a naive value as *local* time — that
        shifted the cached token lifetime by the machine's UTC offset (tokens
        refreshed on every request east of UTC, served expired west of it).
        Naive values are therefore interpreted as UTC; aware datetimes keep
        their own instant and plain numbers are passed through.
        """
        if expiry is None:
            return None
        if isinstance(expiry, (int, float)):
            return float(expiry)
        if isinstance(expiry, datetime.datetime):
            if expiry.tzinfo is None:
                return calendar.timegm(expiry.timetuple())
            return expiry.timestamp()
        return None

    @classmethod
    def _scopes(cls, options: Dict[str, Any]) -> List[str]:
        raw = str(
            options.get("scopes") or os.environ.get("LLM_ROUTER_GOOGLE_SCOPES") or ""
        )
        scopes = [s.strip() for s in raw.split(",") if s.strip()]
        return scopes or [DEFAULT_SCOPE]

    @classmethod
    def _cache_key(cls, options: Dict[str, Any]) -> str:
        return (
            f"{options.get('credentials_file') or ''}"
            f"|{os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')}"
            f"|{'|'.join(cls._scopes(options))}"
        )

    @staticmethod
    def _build_credentials(scopes: List[str], credentials_file: str) -> Any:
        if credentials_file:
            from google.oauth2 import (  # type: ignore[import-not-found]
                service_account,
            )

            return service_account.Credentials.from_service_account_file(
                credentials_file, scopes=scopes
            )
        credentials, _project = google_auth.default(scopes=scopes)
        return credentials

    @classmethod
    def _resolve_token(
        cls, scopes: List[str], credentials_file: str
    ) -> Tuple[str, float]:
        """
        Mint a fresh access token and pair it with its expiry timestamp.

        Credentials without a usable expiry fall back to :data:`_FALLBACK_TTL_SECONDS`.
        """
        try:
            credentials = cls._build_credentials(scopes, credentials_file)
            credentials.refresh(Request())
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"Failed to obtain a Google access token: {exc}"
            ) from exc

        if credentials.token is None:
            raise RuntimeError("Google credentials did not yield a token.")

        expires_at = cls._to_epoch(getattr(credentials, "expiry", None))
        if expires_at is None:
            expires_at = time.time() + _FALLBACK_TTL_SECONDS
        return str(credentials.token), expires_at

    @classmethod
    def get_token(cls, provider_options: Optional[Dict[str, Any]] = None) -> str:
        """
        Return a valid Google access token for the given provider options.

        Parameters
        ----------
        provider_options : Optional[Dict[str, Any]]
            The provider's ``provider_options`` mapping; may carry
            ``credentials_file`` and ``scopes``.

        Returns
        -------
        str
            A fresh (or cached) access token.

        Raises
        ------
        RuntimeError
            When ``google-auth`` is not installed, or when no credential
            source can be resolved.
        """
        if not _GOOGLE_AUTH_AVAILABLE:
            raise RuntimeError(
                "google-auth is not installed – cannot resolve a Google "
                "access token. Install the 'google' extra: "
                "pip install 'radlab-llm-router[google]' (or set "
                "'api_token' on the provider)."
            )

        options = dict(provider_options or {})
        scopes = cls._scopes(options)
        credentials_file = str(options.get("credentials_file") or "").strip()
        key = cls._cache_key(options)

        cached = cls._cached_token(key)
        if cached is not None:
            return cached

        with cls._refresh_lock(key):
            # A thread queued behind this one may have minted the token already;
            # without the re‑check every queued request would mint its own.
            cached = cls._cached_token(key)
            if cached is not None:
                return cached
            token, expires_at = cls._resolve_token(scopes, credentials_file)
            with cls._LOCK:
                cls._CACHE[key] = (token, expires_at)
            logger.debug("Resolved Google access token (source=%s)", key or "ADC")
            return token
