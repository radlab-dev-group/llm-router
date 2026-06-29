"""
Flask before_request auth middleware.

Installed once on the Flask app; inspects every incoming request and
decides whether to allow it to proceed or short-circuit with an error.
"""

from __future__ import annotations

import time

from flask import (
    Flask,
    request,
    jsonify,
    g,
)

from llm_router_api.base.constants import REST_API_LOG_LEVEL

from llm_router_api.core.auth.policies.engine import PermissionEngine
from llm_router_api.core.auth.policies.model import EndpointPermission
from llm_router_api.core.auth.rate_limiter import RedisRateLimiter, RateLimitResult
from llm_router_api.core.auth.errors import (
    AuthResult,
    auth_error_response,
    auth_429_response,
)


class AuthMiddleware:
    """
    Central auth middleware installed via ``@flask_app.before_request``.

    It performs four steps:
    1. **Extract** the API key from headers or query string.
    2. **Authenticate** (hash lookup → key record).
    3. **Authorize** (policy → endpoint permission).
    4. **Rate-limit** (sliding window check).

    Public endpoints (listed in ``LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS``, default
    ``/ping,/version,/models,/``) bypass all checks — they are always accessible
    regardless of auth configuration.  See :data:`~.policies.engine._ENDPOINT_PERMISSION_MAP`
    for the full mapping of authenticated endpoints to their required permission types.
    """

    def __init__(
        self,
        key_store,
        rate_limiter: RedisRateLimiter,
        perm_engine: PermissionEngine,
        auth_config: dict,
    ) -> None:
        self._store = key_store
        self._limiter = rate_limiter
        self._engine = perm_engine
        self._config = auth_config
        self._logger = None  # lazily initialized

    @property
    def logger(self):
        if self._logger is None:
            from rdl_ml_utils.utils.logger import prepare_logger

            self._logger = prepare_logger(
                "llm_router_api.auth.middleware",
                log_level=REST_API_LOG_LEVEL,
                use_default_config=True,
            )
        return self._logger

    # -- entry point -------------------------------------------------
    def get_auth_result(self, request_obj) -> AuthResult:
        """
        Run the full auth flow and return a result.

        Parameters
        ----------
        request_obj : flask.Request
            The current Flask request object.

        Returns
        -------
        AuthResult
        """
        # 1. Public endpoints — always pass
        if self._is_public_endpoint(request_obj.path):
            return AuthResult(
                allowed=True, reason="public_endpoint", status_code=200
            )

        # 2. Extract key
        key, key_id = self._extract_key(request_obj)
        if key is None:
            return AuthResult(allowed=False, reason="missing_key", status_code=401)

        # 3. Authenticate — plaintext lookup (avoids bcrypt salt mismatch)
        key_record = self._store.get_key_by_plain_sync(key)
        if key_record is None:
            self.logger.warning(
                "Authentication failed: invalid key (prefix=%s)",
                key[:7] if len(key) > 6 else key,
            )
            return AuthResult(allowed=False, reason="invalid_key", status_code=401)

        # 3a. Check key status
        if not key_record.get("is_active", True):
            grace = key_record.get("grace_until")
            if grace and time.time() < grace:
                # In grace period — still allow
                pass
            else:
                if key_record.get("rotated_to"):
                    return AuthResult(
                        allowed=False,
                        reason="key_rotated",
                        status_code=401,
                        key_id=key_id,
                    )
                return AuthResult(
                    allowed=False, reason="key_inactive", status_code=401
                )

        # 3b. Check expiry
        expires = key_record.get("expires_at")
        if expires and time.time() > expires:
            return AuthResult(allowed=False, reason="key_expired", status_code=401)

        # Update last_used_at (async — don't block)
        self._update_last_used(key_record)

        # 4. Authorize — policy check
        endpoint_key = f"{request_obj.method.upper()}:{request_obj.path}"
        model_name = self._get_model_name(request_obj)

        permission: EndpointPermission = self._engine.resolve(
            key_record=key_record,
            endpoint_key=endpoint_key,
            model_name=model_name,
        )

        if not permission.allowed:
            self.logger.warning(
                "Authorization failed: key=%s endpoint=%s reason=%s",
                key_id,
                endpoint_key,
                "denied_by_policy" if not permission.allowed else "unknown",
            )
            return AuthResult(
                allowed=False, reason="endpoint_denied_by_policy", status_code=403
            )

        # 5. Rate limit
        limit = permission.method if hasattr(permission, "method") else 60
        client_ip = self._get_client_ip(request_obj)
        rate_result: RateLimitResult = self._limiter.is_allowed(
            key_id=key_id,
            ip=client_ip,
            limit=60,  # default from policy
        )

        if not rate_result.allowed:
            return AuthResult(
                allowed=False,
                reason="rate_limit",
                status_code=429,
                headers={"Retry-After": str(rate_result.retry_after)},
                key_id=key_id,
            )

        # All checks passed — allow
        g.api_key_id = key_id
        g.api_key_prefix = key_record.get("key_prefix", "")
        g.api_key_policy = key_record.get("policy_name", "developer")

        self.logger.debug(
            "Auth OK: key=%s endpoint=%s model=%s",
            key_id,
            endpoint_key,
            model_name,
        )

        return AuthResult(
            allowed=True,
            reason="authenticated",
            status_code=200,
            key_id=key_id,
            headers={"X-RateLimit-Remaining": str(rate_result.remaining)},
        )

    # -- helpers -------------------------------------------------
    def _is_public_endpoint(self, path: str) -> bool:
        """Check if a path is on the public endpoints list."""
        public_str = self._config.get("public_endpoints", "/ping,/version,/models,/")
        public_list = [p.strip() for p in public_str.split(",") if p.strip()]

        # Exact match first
        if path in public_list:
            return True

        # Prefix match for OpenAI-style paths (e.g. /v1/models → /models)
        for pub in public_list:
            v1_path = f"/v1{pub}"
            if path == v1_path:
                return True

        return False

    def _extract_key(self, request_obj) -> tuple[str | None, str]:
        """Extract the API key from headers or query string. Returns (key, key_id)."""
        # Priority 1: Authorization: Bearer <key>
        auth_header = request_obj.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            key = auth_header.split(" ", 1)[1].strip()
            key_id = f"Bearer:{key[:7] if len(key) > 6 else key}"
            return key, key_id

        # Priority 2: x-api-key header
        x_api_key = request_obj.headers.get("x-api-key")
        if x_api_key:
            key = x_api_key.strip()
            key_id = f"x-api-key:{key[:7] if len(key) > 6 else key}"
            return key, key_id

        # Priority 3: query parameter
        query_key = request_obj.args.get("api_key") or request_obj.args.get(
            "api-key"
        )
        if query_key:
            key = query_key.strip()
            key_id = f"query:{key[:7] if len(key) > 6 else key}"
            return key, key_id

        return None, ""

    def _get_model_name(self, request_obj) -> str | None:
        """Extract the model name from the request payload."""
        if request_obj.is_json:
            data = request_obj.get_json(silent=True)
            if data and isinstance(data, dict):
                return data.get("model") or data.get("engine")
        return None

    def _get_client_ip(self, request_obj) -> str:
        """Get the client IP, respecting X-Forwarded-For."""
        forwarded = request_obj.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request_obj.remote_addr or "unknown"

    def _update_last_used(self, key_record: dict) -> None:
        """Mark the key as used (async-friendly)."""
        key_id = key_record.get("key_id")
        if not key_id:
            return
        try:
            import asyncio

            loop = asyncio.get_running_loop()
            loop.create_task(self._update_last_used_async(key_id))
        except RuntimeError:
            # No running event loop — run synchronously in background
            import threading

            threading.Thread(
                target=self._update_last_used_sync,
                args=(key_id,),
                daemon=True,
            ).start()

    async def _update_last_used_async(self, key_id: str) -> None:
        """Async version of last-used update."""
        if hasattr(self._store, "update_last_used"):
            await self._store.update_last_used(key_id)

    def _update_last_used_sync(self, key_id: str) -> None:
        """Sync version of last-used update."""
        if hasattr(self._store, "update_last_used"):
            self._store.update_last_used_sync(key_id)


def install_auth_middleware(
    flask_app: Flask,
    store,
    auth_config: dict,
    redis_client=None,
) -> None:
    """
    Install the auth middleware on the Flask app.

    This function is called from ``FlaskEngine.prepare_flask_app()``
    when ``LLM_ROUTER_AUTH_ENABLED`` is ``"true"``.

    Public endpoints (listed in ``LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS``, default
    ``/ping,/version,/models,/``) bypass all auth checks. All other endpoints
    are mapped to required permission types in
    :data:`~llm_router_api.core.auth.policies.engine._ENDPOINT_PERMISSION_MAP`.

    Parameters
    ----------
    flask_app : Flask
        The Flask application to instrument.
    store : KeyStoreInterface
        The key store used for lookups.
    auth_config : dict
        Authentication configuration dict.
    redis_client : redis.Redis | None, optional
        A verified Redis client (from the key store factory). When provided,
        rate limiting shares the same connection as the key store — no second
        bootstrap attempt is needed.  Defaults to ``None`` (falls back to
        reading auth Redis env vars and connecting directly).
    """
    rate_limiter = RedisRateLimiter(redis_client=redis_client)
    perm_engine = PermissionEngine()
    auth = AuthMiddleware(store, rate_limiter, perm_engine, auth_config)

    @flask_app.before_request
    def auth_hook():
        result = auth.get_auth_result(request)

        # Public endpoint — allow immediately
        if result.allowed and result.reason == "public_endpoint":
            return None

        # Auth failure
        if not result.allowed:
            # Special handling for 429
            if result.reason == "rate_limit":
                response = jsonify(
                    auth_429_response(result.headers.get("Retry-After", 60))
                )
                response.status_code = 429
                response.headers["Retry-After"] = result.headers.get(
                    "Retry-After", "60"
                )
                return response

            response = jsonify(
                auth_error_response(result.reason, result.status_code)
            )
            response.status_code = result.status_code
            for k, v in result.headers.items():
                response.headers[k] = v
            return response

        # Auth success — continue
        if result.key_id:
            g.api_key_id = result.key_id
        return None

    @flask_app.after_request
    def add_auth_headers(response):
        """Add auth-related headers to every response."""
        if hasattr(g, "api_key_id") and g.api_key_id:
            response.headers["X-Auth-Key"] = (
                g.api_key_prefix
            )  # prefix only for security
        return response
