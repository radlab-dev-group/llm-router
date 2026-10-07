"""
Optional AWS credential resolution and SigV4 request signing for Bedrock
providers.

Two responsibilities live here, both deliberately free of any AWS SDK
dependency in the request path:

1. :class:`AwsCredentialProvider` – resolve the credentials a request is
   signed with.  Resolution order:

   a. ``provider_options`` (``access_key_id`` / ``secret_access_key`` /
      ``session_token``);
   b. the standard ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY`` /
       ``AWS_SESSION_TOKEN`` environment variables;
   c. the boto3 credential chain – shared config files, SSO, IAM user roles,
      EKS Web Identity (IRSA) and the EC2/ECS metadata service – through the
      **optional** ``aws`` extra.

2. :class:`AwsSigV4Signer` – Signature Version 4 over a *concrete* request
   body, built from :mod:`hmac` and :mod:`hashlib` only.

``boto3`` is optional (``pip install radlab-llm-router[aws]``).  When it is
missing the module still imports and the static sources above keep working;
:class:`AwsCredentialProvider` raises a :class:`RuntimeError` with the install
hint only when it actually needs the SDK, so the router keeps serving every
other provider type.

The signing name for Amazon Bedrock inference is ``bedrock`` and the endpoint
is region specific (``bedrock-runtime.<region>.amazonaws.com``).
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote, urlsplit

logger = logging.getLogger(__name__)

try:  # optional dependency – see the module docstring
    import boto3  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - exercised via mock in tests
    boto3 = None

_BOTO3_AVAILABLE = boto3 is not None

#: SigV4 service name of the Bedrock runtime endpoint.
BEDROCK_SIGNING_NAME = "bedrock"

#: Algorithm identifier that appears in the ``Authorization`` header.
SIGNING_ALGORITHM = "AWS4-HMAC-SHA256"

#: Expiring credentials (STS, IRSA, metadata service) are refreshed this many
#: seconds before their expiry.  A malformed value must not break import.
try:
    CREDENTIAL_REFRESH_SKEW_SECONDS = int(
        os.environ.get("LLM_ROUTER_AWS_TOKEN_REFRESH_SKEW", 300)
    )
except (TypeError, ValueError):
    CREDENTIAL_REFRESH_SKEW_SECONDS = 300

#: Fallback lifetime (seconds) for credentials that report no expiry.
_FALLBACK_TTL_SECONDS = 3000

_INSTALL_HINT = (
    "boto3 is not installed – cannot resolve the AWS credential chain. "
    "Install the 'aws' extra: pip install 'radlab-llm-router[aws]' (or set "
    "'access_key_id'/'secret_access_key' in the provider's provider_options, "
    "or the AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY environment variables)."
)


class AwsCredentials:
    """
    A resolved set of AWS credentials.

    Attributes
    ----------
    access_key : str
        Access key identifier.
    secret_key : str
        Secret access key used as the SigV4 signing secret.
    session_token : str
        Session token of temporary credentials, empty for long-lived keys.
    expires_at : float
        POSIX timestamp at which the credentials stop being usable.
    source : str
        Human readable origin, kept for log lines (never a secret).
    """

    __slots__ = ("access_key", "secret_key", "session_token", "expires_at", "source")

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        session_token: str = "",
        expires_at: float = 0.0,
        source: str = "static",
    ) -> None:
        self.access_key = access_key
        self.secret_key = secret_key
        self.session_token = session_token
        self.expires_at = expires_at
        self.source = source

    def expires_soon(self) -> bool:
        """True when the credentials are at (or past) the refresh horizon."""
        if self.expires_at <= 0:
            return False
        return time.time() >= self.expires_at - CREDENTIAL_REFRESH_SKEW_SECONDS


class AwsCredentialProvider:
    """
    Resolve and cache AWS credentials for Bedrock providers.

    The cache is process-wide and keyed by the credential source and the
    region, so gunicorn workers each keep their own material without a shared
    store.  Static credentials are returned as‑is; only chain‑resolved
    (temporary) credentials are cached, because those are the ones that go
    stale mid‑flight.
    """

    _LOCK = threading.Lock()
    _CACHE: Dict[str, AwsCredentials] = {}
    #: Per‑key refresh locks: they stop a burst of concurrent requests from
    #: resolving the same role over and over, without holding ``_LOCK`` across
    #: the (network) resolution.  Entries are never dropped, since swapping the
    #: locks would let two threads refresh the same credential at once again.
    _REFRESH_LOCKS: Dict[str, threading.Lock] = {}

    @classmethod
    def clear_cache(cls) -> None:
        """
        Drop all cached credentials (used by tests and credential rotation).

        Only ``_CACHE`` is cleared — the per‑key refresh locks are deliberately
        kept, since discarding them would break the mutual exclusion of any
        resolution already in flight.
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
        Forget the cached credentials of ``provider_options`` (used on 401/403).

        Best‑effort: the next request — or the next monitor ping — resolves
        fresh material instead of replaying credentials the upstream rejected.
        """
        key = cls._cache_key(dict(provider_options or {}))
        with cls._LOCK:
            dropped = cls._CACHE.pop(key, None)
        if dropped is not None:
            logger.debug(
                "Evicted rejected AWS credentials (source=%s)", dropped.source
            )

    # ------------------------------------------------------------------
    # Sources
    # ------------------------------------------------------------------
    @staticmethod
    def _from_options(options: Dict[str, Any]) -> Optional[AwsCredentials]:
        """
        Static credentials supplied inline through ``provider_options``.

        An explicit ``session_token`` is honoured, so long‑lived IAM users and
        pre‑minted STS pairs both work without the SDK.
        """
        access_key = str(
            options.get("access_key_id") or options.get("aws_access_key_id") or ""
        ).strip()
        secret_key = str(
            options.get("secret_access_key")
            or options.get("aws_secret_access_key")
            or ""
        ).strip()
        if not access_key or not secret_key:
            return None
        return AwsCredentials(
            access_key=access_key,
            secret_key=secret_key,
            session_token=str(
                options.get("session_token")
                or options.get("aws_session_token")
                or ""
            ).strip(),
            expires_at=0.0,
            source="provider_options",
        )

    @staticmethod
    def _from_environment() -> Optional[AwsCredentials]:
        """
        Static credentials from the standard AWS environment variables.
        """
        access_key = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
        secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
        if not access_key or not secret_key:
            return None
        return AwsCredentials(
            access_key=access_key,
            secret_key=secret_key,
            session_token=os.environ.get("AWS_SESSION_TOKEN", "").strip(),
            expires_at=0.0,
            source="environment",
        )

    @staticmethod
    def _from_boto3(profile: str = "", region: str = "") -> AwsCredentials:
        """
        Resolve through the boto3 credential chain.

        Covers the sources that are impractical to reimplement by hand —
        shared config files and named profiles, SSO, assume‑role chains, EKS
        Web Identity (IRSA) and the EC2/ECS metadata service — which is exactly
        why ``boto3`` is the optional extra rather than a hard dependency.
        """
        if not _BOTO3_AVAILABLE:
            raise RuntimeError(_INSTALL_HINT)
        try:
            session = boto3.Session(
                profile_name=profile or None, region_name=region or None
            )
            credentials = session.get_credentials()
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Failed to resolve AWS credentials: {exc}") from exc

        if credentials is None:
            raise RuntimeError(
                "The AWS credential chain produced no credentials. Set "
                "provider_options.access_key_id/secret_access_key, the "
                "AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY environment "
                "variables, or a configured AWS profile/role."
            )

        frozen = credentials.get_frozen_credentials()
        if not frozen.access_key or not frozen.secret_key:
            raise RuntimeError(
                "The AWS credential chain produced an incomplete pair."
            )

        expires_at = 0.0
        expiry = getattr(frozen, "expiry_time", None)
        if isinstance(expiry, datetime.datetime):
            expires_at = AwsCredentialProvider._to_epoch(expiry)
        if expires_at <= 0:
            # Long-lived keys report no expiry; cache them for a bounded window
            # so a rotated key is picked up without a restart.
            expires_at = time.time() + _FALLBACK_TTL_SECONDS

        return AwsCredentials(
            access_key=str(frozen.access_key),
            secret_key=str(frozen.secret_key),
            session_token=str(frozen.token or ""),
            expires_at=expires_at,
            source=f"boto3:{session.profile_name or 'default'}",
        )

    @staticmethod
    def _to_epoch(expiry: Any) -> float:
        """
        Convert a credential expiry into a POSIX timestamp.

        boto3 returns an **aware** datetime in UTC, but a naive value read
        through ``datetime.timestamp()`` would be taken as *local* time and
        shift the cache lifetime by the machine's UTC offset — so naive values
        are interpreted as UTC here, exactly as the Google provider does.
        """
        if expiry is None:
            return 0.0
        if isinstance(expiry, (int, float)):
            return float(expiry)
        if isinstance(expiry, datetime.datetime):
            if expiry.tzinfo is None:
                import calendar

                return float(calendar.timegm(expiry.timetuple()))
            return expiry.timestamp()
        return 0.0

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------
    @classmethod
    def _cache_key(cls, options: Dict[str, Any]) -> str:
        profile = str(options.get("profile") or os.environ.get("AWS_PROFILE", ""))
        region = cls.resolve_region(options)
        return f"profile={profile}|region={region}"

    @staticmethod
    def resolve_region(options: Optional[Dict[str, Any]] = None) -> str:
        """
        Resolve the AWS region: ``provider_options.region`` →
        ``AWS_REGION`` → ``AWS_DEFAULT_REGION`` → the boto3 session default.

        Returns
        -------
        str
            The region, or an empty string when nothing configured it and the
            SDK is unavailable to answer.
        """
        options = dict(options or {})
        for key in ("region", "aws_region"):
            value = str(options.get(key) or "").strip()
            if value:
                return value
        for name in ("AWS_REGION", "AWS_DEFAULT_REGION"):
            value = os.environ.get(name, "").strip()
            if value:
                return value
        if _BOTO3_AVAILABLE:
            try:
                profile = str(options.get("profile") or "") or None
                return str(boto3.Session(profile_name=profile).region_name or "")
            except Exception:  # pylint: disable=broad-except
                logger.debug("boto3 could not report a region", exc_info=True)
        return ""

    @classmethod
    def get_credentials(
        cls, provider_options: Optional[Dict[str, Any]] = None
    ) -> AwsCredentials:
        """
        Return usable AWS credentials for the given provider options.

        Parameters
        ----------
        provider_options : Optional[Dict[str, Any]]
            The provider's ``provider_options`` mapping; may carry
            ``access_key_id``/``secret_access_key``/``session_token``,
            ``profile`` and ``region``.

        Returns
        -------
        AwsCredentials
            Static or cached chain‑resolved credentials.

        Raises
        ------
        RuntimeError
            When no source yields credentials, or when the chain is needed but
            ``boto3`` is not installed.
        """
        options = dict(provider_options or {})

        static = cls._from_options(options) or cls._from_environment()
        if static is not None:
            return static

        key = cls._cache_key(options)
        cached = cls._cached_credentials(key)
        if cached is not None:
            return cached

        with cls._refresh_lock(key):
            # A thread queued behind this one may have resolved the credentials
            # already; without the re-check every queued request would assume
            # the same role on its own.
            cached = cls._cached_credentials(key)
            if cached is not None:
                return cached
            resolved = cls._from_boto3(
                profile=str(options.get("profile") or ""),
                region=cls.resolve_region(options),
            )
            with cls._LOCK:
                cls._CACHE[key] = resolved
            logger.debug("Resolved AWS credentials (source=%s)", resolved.source)
            return resolved

    @classmethod
    def _cached_credentials(cls, key: str) -> Optional[AwsCredentials]:
        """Return the cached credentials of ``key`` while outside the skew."""
        with cls._LOCK:
            cached = cls._CACHE.get(key)
        if cached is None or cached.expires_soon():
            return None
        return cached


class AwsSigV4Signer:
    """
    Signature Version 4 signer for Amazon Bedrock runtime requests.

    Implemented over :mod:`hmac`/:mod:`hashlib` so signing adds no dependency.
    The caller hands over the **exact body bytes** that will be transmitted:
    SigV4 signs the payload hash, so a body re‑serialised after signing (what
    ``requests`` does for ``json=``) invalidates the signature.
    """

    @classmethod
    def sign(
        cls,
        method: str,
        url: str,
        headers: Dict[str, str],
        body: Optional[bytes],
        region: str,
        credentials: AwsCredentials,
        service: str = BEDROCK_SIGNING_NAME,
        timestamp: Optional[datetime.datetime] = None,
        include_content_hash: bool = False,
    ) -> Dict[str, str]:
        """
        Return ``headers`` augmented with the SigV4 authentication material.

        Parameters
        ----------
        method : str
            HTTP verb, as it will be sent.
        url : str
            Absolute request URL.
        headers : Dict[str, str]
            The headers the request will carry (``host`` is added if absent).
        body : Optional[bytes]
            The exact transmitted body, or ``None`` for a bodyless request.
        region : str
            AWS region of the endpoint (``eu-central-1``).
        credentials : AwsCredentials
            Credentials to sign with.
        service : str
            Signing name; ``bedrock`` for the runtime endpoint.
        timestamp : Optional[datetime.datetime]
            UTC signing time; defaults to now.  Injectable for tests.
        include_content_hash : bool
            Also send and sign ``x-amz-content-sha256``.  Off by default
            because the Bedrock runtime neither requires nor boto sends it
            (only S3 does), and adding it changes ``SignedHeaders``.

        Returns
        -------
        Dict[str, str]
            A **new** header mapping: the input plus ``x-amz-date``,
            ``x-amz-security-token`` (temporary credentials only) and
            ``Authorization``; ``x-amz-content-sha256`` is added only when
            ``include_content_hash`` is set.
        """
        if not region:
            raise ValueError(
                "AWS region is required to sign a Bedrock request. Set "
                "provider_options.region or AWS_REGION."
            )

        moment = timestamp or datetime.datetime.now(datetime.timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=datetime.timezone.utc)
        amz_date = moment.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = moment.strftime("%Y%m%d")

        parts = urlsplit(url)
        host = parts.netloc
        if not host:
            raise ValueError(
                f"Cannot sign a request without an absolute host: {url!r}"
            )

        signed = dict(headers)
        signed.pop("Authorization", None)
        signed["host"] = signed.get("host") or host
        signed["x-amz-date"] = amz_date
        payload_hash = cls.payload_hash(body)
        if include_content_hash:
            # S3 requires the header; the Bedrock runtime does not, and boto
            # sends it only there.  The payload is covered by the canonical
            # request either way, so omitting it keeps the signature just as
            # binding over the body.
            signed["x-amz-content-sha256"] = payload_hash
        if credentials.session_token:
            signed["x-amz-security-token"] = credentials.session_token

        canonical_headers, signed_headers = cls._canonical_headers(signed)
        canonical_request = "\n".join(
            [
                method.upper(),
                cls._canonical_uri(parts.path),
                cls._canonical_query_string(parts.query),
                canonical_headers,
                signed_headers,
                payload_hash,
            ]
        )

        credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
        string_to_sign = "\n".join(
            [
                SIGNING_ALGORITHM,
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )

        signing_key = cls._signing_key(
            credentials.secret_key, date_stamp, region, service
        )
        signature = hmac.new(
            signing_key, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        signed["Authorization"] = (
            f"{SIGNING_ALGORITHM} "
            f"Credential={credentials.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, "
            f"Signature={signature}"
        )
        return signed

    # ------------------------------------------------------------------
    # Canonicalisation
    # ------------------------------------------------------------------
    @staticmethod
    def payload_hash(body: Optional[bytes]) -> str:
        """Hex SHA‑256 of the body; an absent body hashes as the empty string."""
        return hashlib.sha256(body or b"").hexdigest()

    @staticmethod
    def _canonical_uri(path: str) -> str:
        """
        Percent‑encode the request path the way the service canonicalises it.

        Bedrock model identifiers carry colons (``…-v1:0``, inference profiles,
        model ARNs) and SigV4 signs them as ``%3A`` — verified against
        ``botocore.auth.SigV4Auth.canonical_request``, which encodes
        ``/model/anthropic.claude-3-5-sonnet-20240620-v1:0/converse`` as
        ``/model/anthropic.claude-3-5-sonnet-20240620-v1%3A0/converse`` while
        leaving the transmitted URL untouched.  The service canonicalises the
        path before verifying, so signing the encoded form of a path sent raw
        is what every boto3 Bedrock call does; encoding only the reserved
        characters (and keeping ``/`` and the unreserved set) reproduces it.
        """
        if not path:
            return "/"
        return quote(path, safe="/~")

    @staticmethod
    def _canonical_query_string(query: str) -> str:
        """
        Order the query string as SigV4 requires, keeping it as written.

        The parameters are already percent-encoded by whoever built the URL, so
        the values must be sorted **verbatim**: decoding and re‑encoding here
        would turn ``nextToken=abc%2Fdef`` into ``abc%252Fdef`` and break the
        signature.  This mirrors ``botocore``'s canonicalisation, which splits
        on ``&``, sorts by key and rejoins without touching the encodings.
        """
        if not query:
            return ""
        pairs = sorted(pair for pair in query.split("&") if pair and "=" in pair)
        return "&".join(pairs)

    @staticmethod
    def _canonical_headers(headers: Dict[str, str]) -> Tuple[str, str]:
        """
        Build the canonical header block and the ``SignedHeaders`` list.

        Names are lowercased and trimmed, values collapsed, and everything is
        ordered by name — the three ways a hand-rolled SigV4 most often breaks.
        """
        prepared: Dict[str, str] = {}
        for name, value in headers.items():
            if value is None:
                continue
            lowered = str(name).strip().lower()
            if lowered in (
                "authorization",
                "user-agent",
                "expect",
                "transfer-encoding",
            ):
                # Hop-by-hop and the signature itself are never signed.
                continue
            prepared[lowered] = " ".join(str(value).split())
        names = sorted(prepared)
        block = "".join(f"{name}:{prepared[name]}\n" for name in names)
        return block, ";".join(names)

    @staticmethod
    def _signing_key(
        secret_key: str, date_stamp: str, region: str, service: str
    ) -> bytes:
        """
        Derive the dated, regional, service-scoped signing key.
        """

        def _hmac(key: bytes, message: str) -> bytes:
            return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

        k_date = _hmac(("AWS4" + secret_key).encode("utf-8"), date_stamp)
        k_region = _hmac(k_date, region)
        k_service = _hmac(k_region, service)
        return _hmac(k_service, "aws4_request")
