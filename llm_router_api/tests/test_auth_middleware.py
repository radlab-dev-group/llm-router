"""
Tests for AuthMiddleware — client-IP resolution (trusted proxies), failed-auth
lockout, and the auth decision flow.

Conventions follow the other llm_router_api tests: ``LLM_ROUTER_MINIMUM``
must be set before importing llm_router_api.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")

from llm_router_api.core.auth.errors import auth_429_response
from llm_router_api.core.auth.middleware import AuthMiddleware
from llm_router_api.core.auth.policies.engine import PermissionEngine
from llm_router_api.core.auth.rate_limiter import RedisRateLimiter
from llm_router_api.tests.test_rate_limiter import FakeRedis


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class FakeRequest:
    """
    Minimal stand-in for a Flask request object.
    """

    def __init__(
        self,
        path: str = "/ping",
        method: str = "GET",
        headers: dict | None = None,
        remote_addr: str = "203.0.113.10",
        args: dict | None = None,
        json_data: dict | None = None,
    ) -> None:
        self.path = path
        self.method = method
        self.headers = headers or {}
        self.remote_addr = remote_addr
        self.args = args or {}
        self._json = json_data

    @property
    def is_json(self) -> bool:
        return self._json is not None

    def get_json(self, silent: bool = True):
        return self._json


class FakeStore:
    """
    Key store returning a fixed record for any plaintext lookup.
    """

    def __init__(self, record: dict | None) -> None:
        self._record = record
        self.last_used_calls: list[str] = []

    def get_key_by_plain_sync(self, key_plain: str):
        return self._record

    def update_last_used_sync(self, key_id: str) -> None:
        self.last_used_calls.append(key_id)


def _active_record(**overrides) -> dict:
    rec = {
        "key_id": "key-test",
        "key_hash": "$2b$12$dummy",
        "key_prefix": "sk-test",
        "policy_name": "developer",
        "policy_override": None,
        "is_active": True,
        "expires_at": None,
    }
    rec.update(overrides)
    return rec


def _middleware(store_record, config: dict | None = None) -> AuthMiddleware:
    limiter = RedisRateLimiter(redis_client=FakeRedis(), window=60)
    return AuthMiddleware(
        FakeStore(store_record),
        limiter,
        PermissionEngine(),
        config
        or {
            "public_endpoints": "/, /metrics, /health",
            "auth_failure_limit": 0,
            "trusted_proxies": "",
        },
    )


def _bearer(key: str = "sk-live-abcdef0123456789") -> dict:
    return {"Authorization": f"Bearer {key}"}


class TestClientIpResolution:
    """
    X-Forwarded-For is honoured only from trusted proxies.
    """

    def test_xff_ignored_from_untrusted_peer(self) -> None:
        """
        A direct client sending XFF gets its real remote_addr used.
        """

        mw = _middleware(None, {"trusted_proxies": "10.0.0.0/8"})
        req = FakeRequest(
            remote_addr="203.0.113.10",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert mw._get_client_ip(req) == "203.0.113.10"

    def test_xff_honoured_from_trusted_proxy(self) -> None:
        """
        A trusted proxy's XFF right-most entry is the client IP.
        """

        mw = _middleware(None, {"trusted_proxies": "10.0.0.1"})
        req = FakeRequest(
            remote_addr="10.0.0.1",
            headers={"X-Forwarded-For": "198.51.100.7, 203.0.113.99"},
        )
        # Proxies append: right-most entry is the original client.
        assert mw._get_client_ip(req) == "203.0.113.99"

    def test_xff_honoured_via_cidr(self) -> None:
        """
        Trust matched via CIDR entry.
        """

        mw = _middleware(None, {"trusted_proxies": "10.1.0.0/16"})
        req = FakeRequest(
            remote_addr="10.1.7.25",
            headers={"X-Forwarded-For": "192.0.2.44"},
        )
        assert mw._get_client_ip(req) == "192.0.2.44"

    def test_no_trusted_proxies_configured(self) -> None:
        """
        With an empty trusted list, XFF is always ignored.
        """

        mw = _middleware(None, {"trusted_proxies": ""})
        req = FakeRequest(
            remote_addr="203.0.113.10",
            headers={"X-Forwarded-For": "1.2.3.4"},
        )
        assert mw._get_client_ip(req) == "203.0.113.10"

    def test_csv_trusted_proxies(self) -> None:
        """
        The trusted list may be a CSV string.
        """

        mw = _middleware(None, {"trusted_proxies": "10.0.0.1, 192.168.0.0/24"})
        req = FakeRequest(
            remote_addr="192.168.0.5",
            headers={"X-Forwarded-For": "198.51.100.200"},
        )
        assert mw._get_client_ip(req) == "198.51.100.200"


class TestFailedAuthLockout:
    """
    Failed attempts are throttled per-IP in the __auth_fail__ bucket.
    """

    def test_within_budget_returns_401(self) -> None:
        """
        Below the failure limit the specific 401 reason is preserved.
        """

        mw = _middleware(
            None,
            {"auth_failure_limit": 5, "public_endpoints": "/, /metrics, /health"},
        )
        for _ in range(3):
            result = mw.get_auth_result(FakeRequest())
            assert result.allowed is False
            assert result.reason == "missing_key"
            assert result.status_code == 401

    def test_over_budget_returns_429(self) -> None:
        """
        Past the failure limit the client is locked out with 429.
        """

        mw = _middleware(
            None,
            {"auth_failure_limit": 3, "public_endpoints": "/, /metrics, /health"},
        )
        for _ in range(3):
            mw.get_auth_result(FakeRequest())
        result = mw.get_auth_result(FakeRequest())
        assert result.allowed is False
        assert result.status_code == 429
        assert result.reason == "rate_limit"
        assert int(result.headers["Retry-After"]) >= 1

    def test_invalid_key_also_throttled(self) -> None:
        """
        Invalid-key attempts share the per-IP failure bucket.
        """

        mw = _middleware(
            None,
            {"auth_failure_limit": 2, "public_endpoints": "/, /metrics, /health"},
        )
        for _ in range(2):
            result = mw.get_auth_result(FakeRequest(headers=_bearer("sk-bogus")))
            assert result.reason == "invalid_key"
        result = mw.get_auth_result(FakeRequest(headers=_bearer("sk-bogus")))
        assert result.status_code == 429

    def test_lockout_is_per_ip(self) -> None:
        """
        One locked-out IP does not block a different IP.
        """

        mw = _middleware(
            None,
            {"auth_failure_limit": 1, "public_endpoints": "/, /metrics, /health"},
        )
        first = FakeRequest(remote_addr="203.0.113.1")
        second = FakeRequest(remote_addr="203.0.113.2")

        assert mw.get_auth_result(first).reason == "missing_key"
        assert mw.get_auth_result(first).status_code == 429  # now locked out
        # The second IP is unaffected
        assert mw.get_auth_result(second).reason == "missing_key"

    def test_lockout_disabled_by_default(self) -> None:
        """
        auth_failure_limit=0 (unset) disables lockout entirely.
        """

        mw = _middleware(
            None,
            {"auth_failure_limit": 0, "public_endpoints": "/, /metrics, /health"},
        )
        for _ in range(50):
            result = mw.get_auth_result(FakeRequest())
            assert result.status_code == 401


class TestAuthFlow:
    """
    End-to-end decisions through get_auth_result.
    """

    def test_public_endpoint_passes_without_key(self) -> None:
        mw = _middleware(None)
        result = mw.get_auth_result(FakeRequest(path="/health"))
        assert result.allowed is True
        assert result.reason == "public_endpoint"

    def test_valid_developer_key_allowed(self) -> None:
        # The success path writes flask.g — needs an app context.
        from flask import Flask

        mw = _middleware(_active_record())
        app = Flask(__name__)
        with app.app_context():
            result = mw.get_auth_result(
                FakeRequest(
                    path="/api/chat/completions", method="POST", headers=_bearer()
                )
            )
        assert result.allowed is True
        assert result.reason == "authenticated"
        assert result.status_code == 200

    def test_valid_chat_policy_key_denied_on_embedding(self) -> None:
        """
        Default-deny: a chat-policy key cannot POST embeddings (403).
        """

        mw = _middleware(_active_record(policy_name="chat"))
        result = mw.get_auth_result(
            FakeRequest(path="/v1/embeddings", method="POST", headers=_bearer())
        )
        assert result.allowed is False
        assert result.status_code == 403
        assert result.reason == "endpoint_denied_by_policy"

    def test_inactive_key_rejected(self) -> None:
        mw = _middleware(_active_record(is_active=False, grace_until=None))
        result = mw.get_auth_result(FakeRequest(headers=_bearer()))
        assert result.allowed is False
        assert result.reason == "key_inactive"
        assert result.status_code == 401

    def test_expired_key_rejected(self) -> None:
        import time

        mw = _middleware(_active_record(expires_at=time.time() - 10))
        result = mw.get_auth_result(FakeRequest(headers=_bearer()))
        assert result.allowed is False
        assert result.reason == "key_expired"
        assert result.status_code == 401

    def test_query_string_api_key_rejected(self) -> None:
        """
        Keys passed via query string are rejected (missing_key) and logged.
        """

        mw = _middleware(_active_record())
        result = mw.get_auth_result(FakeRequest(args={"api_key": "sk-whatever"}))
        assert result.allowed is False
        assert result.reason in ("missing_key", "rate_limit")


class Test429Response:
    """
    The 429 body is a single well-formed JSON object.
    """

    def test_single_object_with_retry_after(self) -> None:
        body = auth_429_response(42)
        # A dict (not a tuple/list) with the retry_after inside `error`.
        assert isinstance(body, dict)
        assert isinstance(body["error"], dict)
        assert body["error"]["retry_after"] == 42
        assert body["error"]["type"] == "rate_limit_error"
        assert body["error"]["code"] == 429

    def test_retry_after_is_int(self) -> None:
        assert isinstance(auth_429_response("17")["error"]["retry_after"], int)
