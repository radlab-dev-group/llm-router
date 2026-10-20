"""
Optional Microsoft Entra ID credential handling for Azure OpenAI providers.

The module resolves a Microsoft Entra ID (Azure AD) access token for
providers that do not carry an Azure OpenAI API key.  Sources, in resolution
order:

1. ``provider_options.access_token`` – an explicit bearer token supplied by
   the operator (e.g. minted out of band by ``az account get-access-token``);
   handled by :class:`~llm_router_api.core.api_types.azure_openai.AzureOpenAiType`,
   never cached here because the router does not know its lifetime;
2. ``provider_options.client_id`` / ``client_secret`` (+ ``tenant_id``) –
   the service‑principal client‑credentials flow;
3. a federated workload identity: a client id plus a federated token file
   (``provider_options.federated_token_file`` or the
   ``AZURE_FEDERATED_TOKEN_FILE`` environment variable, as projected by AKS
   Workload Identity) exchanged with the client‑assertion grant;
4. the App Service / Functions / Container Apps identity endpoint
   (``IDENTITY_ENDPOINT`` + ``IDENTITY_HEADER``, legacy
   ``MSI_ENDPOINT`` + ``MSI_SECRET``);
5. the Azure Instance Metadata Service (IMDS) – the managed identity of a
   VM, scale set or AKS node.

Only ``requests`` – already a hard dependency of the router – is used, so no
optional extra has to be installed.  When no source can mint a token,
:meth:`AzureAdTokenProvider.get_token` raises :class:`RuntimeError` naming
every source it tried (with the provider's own diagnostic when one answered),
which is the difference between a five‑minute fix and a long debugging
session.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

logger = logging.getLogger(__name__)

#: Audience (scope) requested for Azure OpenAI tokens when the operator does
#: not override it.  ``/.default`` maps to the scope the resource exposes to
#: the app registration, which is what Entra issues for Azure OpenAI.
DEFAULT_SCOPE = "https://cognitiveservices.azure.com/.default"

#: Public cloud authority.  Sovereign clouds differ; override with
#: ``provider_options.authority_host`` or ``AZURE_AUTHORITY_HOST``.
DEFAULT_AUTHORITY_HOST = "https://login.microsoftonline.com"

#: IMDS: the identity endpoint every Azure compute resource answers on.
IMDS_ENDPOINT = "http://169.254.169.254/metadata/identity/oauth2/token"
#: IMDS api‑version known to answer for the instance identity.
IMDS_API_VERSION = "2018-02-01"
#: App Service / Functions identity api‑version.
APP_SERVICE_IDENTITY_API_VERSION = "2019-08-01"

#: Tokens are refreshed this many seconds before their expiry.  A malformed
#: value must not break module import – fall back to the default.
try:
    TOKEN_REFRESH_SKEW_SECONDS = int(
        os.environ.get("LLM_ROUTER_AZURE_TOKEN_REFRESH_SKEW", 120)
    )
except (TypeError, ValueError):
    TOKEN_REFRESH_SKEW_SECONDS = 120

#: Fallback TTL (seconds) for tokens that report no expiry.
_FALLBACK_TTL_SECONDS = 3000

#: HTTP timeout (seconds) of the Entra ID token endpoint call.
try:
    REQUEST_TIMEOUT_SECONDS = int(
        os.environ.get("LLM_ROUTER_AZURE_REQUEST_TIMEOUT", 10)
    )
except (TypeError, ValueError):
    REQUEST_TIMEOUT_SECONDS = 10

#: HTTP timeout (seconds) of the link‑local identity calls (IMDS / App
#: Service).  Kept short on purpose: off Azure those endpoints either answer
#: immediately or are unreachable, and a long timeout would stall every
#: request of a misconfigured provider instead of failing it fast.
try:
    IDENTITY_ENDPOINT_TIMEOUT_SECONDS = int(
        os.environ.get("LLM_ROUTER_AZURE_IDENTITY_TIMEOUT", 3)
    )
except (TypeError, ValueError):
    IDENTITY_ENDPOINT_TIMEOUT_SECONDS = 3


class AzureAdTokenProvider:
    """
    Resolve and cache Microsoft Entra ID access tokens for Azure OpenAI
    providers.

    The cache is process‑wide and keyed by the credential *source* (client
    id, tenant, scope, identity endpoint), so gunicorn workers each keep
    their own token without a shared store, and two workers using one
    identity share one slot.  Refreshes are serialised **per credential**: a
    burst of concurrent requests mints one token, not one per request.
    """

    _LOCK = threading.Lock()
    _CACHE: Dict[str, Tuple[str, float]] = {}
    #: Per‑credential refresh locks: they keep ``_LOCK`` off the network call
    #: while still preventing a thundering herd on one credential.
    _REFRESH_LOCKS: Dict[str, threading.Lock] = {}

    @classmethod
    def clear_cache(cls) -> None:
        """
        Drop every cached token (used by tests, and by operators reloading
        credentials without a restart).
        """
        with cls._LOCK:
            cls._CACHE.clear()

    @classmethod
    def invalidate(cls, provider_options: Optional[Dict[str, Any]] = None) -> None:
        """
        Evict the cached token of the credential *provider_options* names.

        A ``401``/``403`` from Azure OpenAI means the token the router
        presented was rejected (rotated secret, removed role assignment,
        revoked identity).  Without the eviction every later request replays
        the same rejected credential until the process restarts.
        """
        key = cls._cache_key(provider_options or {})
        with cls._LOCK:
            cls._CACHE.pop(key, None)

    @classmethod
    def _refresh_lock(cls, key: str) -> threading.Lock:
        """
        Return the refresh lock of ``key``, creating it when absent.
        """
        with cls._LOCK:
            return cls._REFRESH_LOCKS.setdefault(key, threading.Lock())

    # ------------------------------------------------------------------
    # Credential source helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _env(name: str) -> str:
        """
        Return the trimmed value of environment variable ``name``.
        """
        return str(os.environ.get(name) or "").strip()

    @classmethod
    def _scope(cls, options: Dict[str, Any]) -> str:
        """
        Return the requested scope: ``provider_options.scope``, the
        ``AZURE_OPENAI_AD_SCOPE``/``AZURE_AD_SCOPE`` environment variables,
        or :data:`DEFAULT_SCOPE`.
        """
        return str(
            options.get("scope")
            or cls._env("AZURE_OPENAI_AD_SCOPE")
            or cls._env("AZURE_AD_SCOPE")
            or DEFAULT_SCOPE
        )

    @classmethod
    def _resource(cls, options: Dict[str, Any]) -> str:
        """
        Return the ``resource`` the identity endpoints ask for: the scope
        without its ``/.default`` suffix (IMDS and the App Service endpoint
        are the pre‑v2 API and speak resources, not scopes).
        """
        return cls._scope(options).rsplit("/.default", 1)[0]

    @classmethod
    def _tenant_id(cls, options: Dict[str, Any]) -> str:
        """
        Return the tenant id: ``provider_options.tenant_id`` (``tenant`` is
        accepted too), ``AZURE_TENANT_ID``, or ``common`` as the last resort.
        """
        return str(
            options.get("tenant_id")
            or options.get("tenant")
            or cls._env("AZURE_TENANT_ID")
            or "common"
        )

    @classmethod
    def _authority_host(cls, options: Dict[str, Any]) -> str:
        """
        Return the Entra authority host (sovereign clouds differ).
        """
        return str(
            options.get("authority_host")
            or cls._env("AZURE_AUTHORITY_HOST")
            or DEFAULT_AUTHORITY_HOST
        ).rstrip("/")

    @classmethod
    def _token_url(cls, options: Dict[str, Any]) -> str:
        """
        Return the OAuth2 token endpoint of the tenant.
        """
        explicit = str(options.get("token_url") or "").strip()
        if explicit:
            return explicit
        return (
            f"{cls._authority_host(options)}/{cls._tenant_id(options)}"
            "/oauth2/v2.0/token"
        )

    @classmethod
    def _federated_token_file(cls, options: Dict[str, Any]) -> str:
        """
        Return the workload identity federation token file, if any.
        """
        return str(
            options.get("federated_token_file")
            or cls._env("AZURE_FEDERATED_TOKEN_FILE")
            or ""
        ).strip()

    @classmethod
    def _client_id(cls, options: Dict[str, Any]) -> str:
        """
        Return the client id of the app registration / user‑assigned identity.
        """
        return str(options.get("client_id") or cls._env("AZURE_CLIENT_ID")).strip()

    @classmethod
    def _client_secret(cls, options: Dict[str, Any]) -> str:
        """
        Return the client secret of the app registration.
        """
        return str(
            options.get("client_secret") or cls._env("AZURE_CLIENT_SECRET")
        ).strip()

    @classmethod
    def _identity_endpoint(cls) -> Tuple[str, str]:
        """
        Return the ``(endpoint, secret)`` pair of the App Service style
        identity endpoint, or ``("", "")`` when the runtime offers none.
        """
        return (
            cls._env("IDENTITY_ENDPOINT") or cls._env("MSI_ENDPOINT"),
            cls._env("IDENTITY_HEADER") or cls._env("MSI_SECRET"),
        )

    @classmethod
    def _cache_key(cls, options: Dict[str, Any]) -> str:
        """
        Identify the credential source a cached token belongs to.

        The key is built from what *selects* the credential (client id,
        tenant, scope, identity endpoint), never from a secret: two workers
        sharing an identity share one slot, while a different identity never
        reads another's token.
        """
        endpoint, _ = cls._identity_endpoint()
        return "|".join(
            (
                cls._client_id(options) or "-",
                cls._tenant_id(options),
                cls._scope(options),
                cls._federated_token_file(options) or "-",
                endpoint or "imds",
            )
        )

    @classmethod
    def _cached_token(cls, key: str) -> Optional[str]:
        """
        Return the cached token of ``key`` when still fresh, else ``None``.
        """
        now = time.time()
        with cls._LOCK:
            entry = cls._CACHE.get(key)
        if entry is None:
            return None
        token, expires_at = entry
        if expires_at - TOKEN_REFRESH_SKEW_SECONDS <= now:
            with cls._LOCK:
                cls._CACHE.pop(key, None)
            return None
        return token

    @classmethod
    def _store(cls, key: str, token: str, expires_in: Any) -> str:
        """
        Cache ``token`` for ``key``, honouring the reported lifetime.
        """
        try:
            lifetime = float(expires_in)
        except (TypeError, ValueError):
            lifetime = 0.0
        if lifetime <= 0:
            lifetime = float(_FALLBACK_TTL_SECONDS)
        with cls._LOCK:
            cls._CACHE[key] = (token, time.time() + lifetime)
        return token

    @staticmethod
    def _failure(reason: str, errors: Optional[List[str]]) -> None:
        """
        Record why a source did not produce a token.

        The reason reaches the :class:`RuntimeError` of :meth:`get_token` —
        kept short and free of secret material by the callers.
        """
        if errors is not None:
            errors.append(reason)

    # ------------------------------------------------------------------
    # Token sources
    # ------------------------------------------------------------------
    @classmethod
    def _from_client_credentials(
        cls,
        options: Dict[str, Any],
        key: str,
        errors: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Mint a token with the client credentials grant: a client secret, or a
        federated workload identity assertion when no secret is configured.
        """
        client_id = cls._client_id(options)
        client_secret = cls._client_secret(options)
        federation_file = cls._federated_token_file(options)

        data: Dict[str, str] = {
            "grant_type": "client_credentials",
            "scope": cls._scope(options),
        }
        if client_secret:
            if not client_id:
                return None
            data["client_id"] = client_id
            data["client_secret"] = client_secret
        elif client_id and federation_file:
            try:
                with open(federation_file, "rt", encoding="utf-8") as handle:
                    assertion = handle.read().strip()
            except OSError as exc:
                logger.warning(
                    "Could not read the workload identity token file %s: %s",
                    federation_file,
                    exc,
                )
                cls._failure(
                    f"workload identity token file {federation_file} "
                    f"is unreadable: {exc}",
                    errors,
                )
                return None
            if not assertion:
                cls._failure(
                    f"workload identity token file {federation_file} is empty",
                    errors,
                )
                return None
            data["client_id"] = client_id
            data["client_assertion_type"] = (
                "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            )
            data["client_assertion"] = assertion
        else:
            # No secret and no federation file: this source is simply not
            # configured, which is not a failure worth reporting.
            return None

        try:
            response = requests.post(
                cls._token_url(options),
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.warning("Microsoft Entra ID token endpoint unreachable: %s", exc)
            cls._failure(f"Entra ID token endpoint unreachable: {exc}", errors)
            return None
        if response.status_code >= 400:
            # The body carries the provider's own diagnostic (``AADSTS…``),
            # which is what makes a rotated secret recognisable; the secret
            # and the assertion itself are never logged nor forwarded.
            detail = (response.text or "").strip()[:300]
            logger.warning(
                "Microsoft Entra ID token request failed (HTTP %s): %s",
                response.status_code,
                detail,
            )
            cls._failure(
                f"Entra ID token endpoint answered HTTP "
                f"{response.status_code}: {detail}",
                errors,
            )
            return None
        payload = response.json() if response.content else {}
        token = str(payload.get("access_token") or "")
        if not token:
            logger.warning(
                "Microsoft Entra ID token response carried no access_token."
            )
            cls._failure("Entra ID token response carried no access_token", errors)
            return None
        return cls._store(key, token, payload.get("expires_in"))

    @classmethod
    def _from_identity_endpoint(
        cls,
        options: Dict[str, Any],
        key: str,
        errors: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Read a token from the App Service / Functions / Container Apps
        identity endpoint.
        """
        endpoint, secret = cls._identity_endpoint()
        if not endpoint or not secret:
            return None
        params: Dict[str, str] = {
            "api-version": APP_SERVICE_IDENTITY_API_VERSION,
            "resource": cls._resource(options),
        }
        client_id = cls._client_id(options)
        if client_id:
            params["client_id"] = client_id
        try:
            response = requests.get(
                endpoint,
                params=params,
                headers={"X-IDENTITY-HEADER": secret},
                timeout=IDENTITY_ENDPOINT_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.debug("App Service identity endpoint unreachable: %s", exc)
            cls._failure("App Service identity endpoint unreachable", errors)
            return None
        if response.status_code != 200:
            logger.debug(
                "App Service identity request answered HTTP %s.",
                response.status_code,
            )
            cls._failure(
                f"App Service identity endpoint answered HTTP "
                f"{response.status_code}",
                errors,
            )
            return None
        payload = response.json() if response.content else {}
        token = str(payload.get("access_token") or "")
        if not token:
            cls._failure(
                "App Service identity endpoint returned no access_token", errors
            )
            return None
        return cls._store(key, token, payload.get("expires_in"))

    @classmethod
    def _from_imds(
        cls,
        options: Dict[str, Any],
        key: str,
        errors: Optional[List[str]] = None,
    ) -> Optional[str]:
        """
        Read the token of the instance's managed identity from IMDS.

        A user‑assigned identity is addressed by its client id, which is
        forwarded when configured; without one IMDS answers with the
        *system‑assigned* identity.
        """
        params: Dict[str, str] = {
            "api-version": IMDS_API_VERSION,
            "resource": cls._resource(options),
        }
        client_id = cls._client_id(options)
        if client_id:
            params["client_id"] = client_id
        try:
            response = requests.get(
                IMDS_ENDPOINT,
                params=params,
                headers={"Metadata": "true"},
                timeout=IDENTITY_ENDPOINT_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            logger.debug("IMDS identity endpoint unreachable: %s", exc)
            cls._failure(f"IMDS unreachable ({exc.__class__.__name__})", errors)
            return None
        if response.status_code != 200:
            logger.debug(
                "IMDS identity request answered HTTP %s; no managed identity "
                "available.",
                response.status_code,
            )
            cls._failure(
                f"IMDS answered HTTP {response.status_code} (no managed "
                f"identity?)",
                errors,
            )
            return None
        payload = response.json() if response.content else {}
        token = str(payload.get("access_token") or "")
        if not token:
            cls._failure("IMDS returned no access_token", errors)
            return None
        return cls._store(key, token, payload.get("expires_in"))

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    @classmethod
    def get_token(cls, provider_options: Optional[Dict[str, Any]] = None) -> str:
        """
        Return a valid Microsoft Entra ID access token for an Azure OpenAI
        provider, resolving it from the first usable credential source and
        caching it until close to its expiry.

        Raises
        ------
        RuntimeError
            When no source can mint a token.  The message lists the sources
            that were tried and, when one answered, what it said.
        """
        options = dict(provider_options or {})
        key = cls._cache_key(options)

        cached = cls._cached_token(key)
        if cached is not None:
            return cached

        with cls._refresh_lock(key):
            cached = cls._cached_token(key)
            if cached is not None:
                return cached

            errors: List[str] = []
            sources: List[Callable[..., Optional[str]]] = [
                cls._from_client_credentials,
                cls._from_identity_endpoint,
                cls._from_imds,
            ]
            for source in sources:
                token = source(options, key, errors)
                if token:
                    return token

            tried = (
                ", ".join(errors)
                if errors
                else (
                    "no source was configured (client credentials, workload "
                    "identity, App Service identity, IMDS)"
                )
            )
            raise RuntimeError(
                "No usable Microsoft Entra ID credential for the Azure "
                f"OpenAI provider — {tried}. Set the Azure API key "
                "(`api_token` / provider_options.api_key) or an explicit "
                "provider_options.access_token, or run on Azure compute "
                "whose identity carries the 'Azure OpenAI User' role."
            )
