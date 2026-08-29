"""
Tests for the permission engine — default-deny type gating, IP whitelist,
monthly token budget, model whitelists, and policy overrides.

Conventions follow the other llm_router_api tests: ``LLM_ROUTER_MINIMUM``
must be set before importing llm_router_api.
"""

from __future__ import annotations

import os
import time

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")

from llm_router_api.core.auth.policies.engine import PermissionEngine
from llm_router_api.core.auth.policies.model import EndpointPolicy

CHAT_EP = "post:/v1/chat/completions"
EMBED_EP = "post:/v1/embeddings"
ANTHROPIC_EP = "post:/v1/messages"
BUILTIN_EP = "post:/api/polarity_3c"
PUBLIC_EP = "get:/health"
UNKNOWN_EP = "post:/api/definitely-not-real"


def _key(**overrides) -> dict:
    """
    Build a minimal active key record.
    """

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


class TestDefaultDeny:
    """
    An endpoint is reachable only if the key's policy grants its type.
    """

    def setup_method(self) -> None:
        self.engine = PermissionEngine()

    def test_developer_policy_grants_all_types(self) -> None:
        """
        The full-access developer role still reaches every endpoint type.
        """

        for ep in (CHAT_EP, EMBED_EP, ANTHROPIC_EP, BUILTIN_EP):
            assert (
                self.engine.resolve(_key(), ep).allowed is True
            ), f"developer should reach {ep}"

    def test_chat_policy_cannot_reach_embedding(self) -> None:
        """
        A chat-only key is denied on embedding endpoints (type gate).
        """

        assert self.engine.resolve(_key(policy_name="chat"), CHAT_EP).allowed is True
        assert (
            self.engine.resolve(_key(policy_name="chat"), EMBED_EP).allowed is False
        )

    def test_embedding_policy_cannot_reach_chat(self) -> None:
        """
        Symmetric: an embedding-only key is denied on chat endpoints.
        """

        assert (
            self.engine.resolve(_key(policy_name="embedding"), EMBED_EP).allowed
            is True
        )
        assert (
            self.engine.resolve(_key(policy_name="embedding"), CHAT_EP).allowed
            is False
        )

    def test_unknown_policy_denies_everything(self) -> None:
        """
        A key referencing a non-existent policy is default-deny.
        """

        for ep in (CHAT_EP, EMBED_EP, ANTHROPIC_EP, BUILTIN_EP):
            assert (
                self.engine.resolve(_key(policy_name="no-such-policy"), ep).allowed
                is False
            ), f"unknown policy must not reach {ep}"

    def test_unknown_endpoint_is_denied(self) -> None:
        """
        An endpoint absent from the permission map is never reachable.
        """

        assert self.engine.resolve(_key(), UNKNOWN_EP).allowed is False

    def test_inactive_key_denied(self) -> None:
        """
        An inactive key is denied even with a full-access policy.
        """

        assert self.engine.resolve(_key(is_active=False), CHAT_EP).allowed is False

    def test_expired_key_denied(self) -> None:
        """
        An expired key is denied even with a full-access policy.
        """

        assert (
            self.engine.resolve(_key(expires_at=time.time() - 10), CHAT_EP).allowed
            is False
        )

    def test_public_endpoint_bypasses_policy(self) -> None:
        """
        Public endpoints are always reachable, even with a deny-all policy.
        """

        assert (
            self.engine.resolve(
                _key(policy_name="no-such-policy"), PUBLIC_EP
            ).allowed
            is True
        )

    def test_policy_with_empty_allowed_types_denies(self) -> None:
        """
        A custom policy that grants no types denies everything.
        """

        engine = PermissionEngine()
        engine.add_custom_policy("empty", EndpointPolicy(can_access=True))
        assert engine.resolve(_key(policy_name="empty"), CHAT_EP).allowed is False


class TestIpWhitelist:
    """
    ``ip_whitelist`` is enforced: outside the list → deny.
    """

    def setup_method(self) -> None:
        self.engine = PermissionEngine()
        self.engine.add_custom_policy(
            "whitelisted",
            EndpointPolicy(
                can_access=True,
                allowed_types=("chat",),
                ip_whitelist=("10.0.0.5", "192.168.1.0/24"),
            ),
        )

    def test_ip_in_whitelist_allowed(self) -> None:
        """
        A client IP exactly in the whitelist is allowed.
        """

        assert (
            self.engine.resolve(
                _key(policy_name="whitelisted"), CHAT_EP, client_ip="10.0.0.5"
            ).allowed
            is True
        )

    def test_ip_in_cidr_allowed(self) -> None:
        """
        A client IP inside a whitelisted CIDR is allowed.
        """

        assert (
            self.engine.resolve(
                _key(policy_name="whitelisted"), CHAT_EP, client_ip="192.168.1.77"
            ).allowed
            is True
        )

    def test_ip_outside_whitelist_denied(self) -> None:
        """
        A client IP outside the whitelist is denied.
        """

        assert (
            self.engine.resolve(
                _key(policy_name="whitelisted"), CHAT_EP, client_ip="8.8.8.8"
            ).allowed
            is False
        )

    def test_missing_client_ip_denied(self) -> None:
        """
        Without a client IP a configured whitelist can never match (deny).
        """

        assert (
            self.engine.resolve(
                _key(policy_name="whitelisted"), CHAT_EP, client_ip=None
            ).allowed
            is False
        )

    def test_no_whitelist_no_restriction(self) -> None:
        """
        A policy without ip_whitelist is unrestricted on IP.
        """

        assert (
            self.engine.resolve(_key(), CHAT_EP, client_ip="8.8.8.8").allowed is True
        )


class TestTokenBudget:
    """
    ``budget_monthly_tokens`` is enforced: used >= budget → deny.
    """

    def setup_method(self) -> None:
        self.engine = PermissionEngine()
        self.engine.add_custom_policy(
            "budgeted",
            EndpointPolicy(
                can_access=True,
                allowed_types=("chat",),
                budget_monthly_tokens=1000,
            ),
        )

    def test_under_budget_allowed(self) -> None:
        """
        Usage below the budget is allowed.
        """

        assert (
            self.engine.resolve(
                _key(policy_name="budgeted"), CHAT_EP, tokens_used=999
            ).allowed
            is True
        )

    def test_at_budget_denied(self) -> None:
        """
        Usage equal to the budget is denied (budget is inclusive).
        """

        assert (
            self.engine.resolve(
                _key(policy_name="budgeted"), CHAT_EP, tokens_used=1000
            ).allowed
            is False
        )

    def test_over_budget_denied(self) -> None:
        """
        Usage above the budget is denied.
        """

        assert (
            self.engine.resolve(
                _key(policy_name="budgeted"), CHAT_EP, tokens_used=1_000_000
            ).allowed
            is False
        )

    def test_falls_back_to_policy_used_counter(self) -> None:
        """
        When no live count is passed, policy.budget_tokens_used is used.
        """

        policy = EndpointPolicy(
            can_access=True,
            allowed_types=("chat",),
            budget_monthly_tokens=100,
            budget_tokens_used=100,
        )
        engine = PermissionEngine()
        engine.add_custom_policy("counter", policy)
        assert engine.resolve(_key(policy_name="counter"), CHAT_EP).allowed is False

    def test_no_budget_no_restriction(self) -> None:
        """
        A policy without a budget never denies on usage.
        """

        assert (
            self.engine.resolve(_key(), CHAT_EP, tokens_used=10**12).allowed is True
        )


class TestModelWhitelist:
    """
    Global and per-endpoint model whitelists are enforced.
    """

    def test_global_model_whitelist(self) -> None:
        """
        A model outside the global whitelist is denied.

        Matching semantics (pre-existing): the requested model name must be
        contained in one of the whitelist entries.
        """

        engine = PermissionEngine()
        engine.add_custom_policy(
            "models",
            EndpointPolicy(
                can_access=True,
                allowed_types=("chat",),
                model_whitelist=("gpt-4o-mini", "gpt-4"),
            ),
        )
        assert (
            engine.resolve(
                _key(policy_name="models"), CHAT_EP, model_name="gpt-4"
            ).allowed
            is True
        )
        assert (
            engine.resolve(
                _key(policy_name="models"), CHAT_EP, model_name="llama-3"
            ).allowed
            is False
        )


class TestPolicyOverride:
    """
    policy_override refines a base policy without breaking default-deny.
    """

    def test_partial_override_inherits_base_types(self) -> None:
        """
        A partial override (e.g. rate-limit only, as written by the CLI)
        keeps the base policy's type grants.
        """

        engine = PermissionEngine()
        rec = _key(policy_name="developer", policy_override={"rate_limit": 10})
        assert engine.resolve(rec, CHAT_EP).allowed is True
        assert engine.resolve(rec, EMBED_EP).allowed is True

    def test_partial_override_applies_rate_limit(self) -> None:
        """
        The overridden rate_limit is surfaced on the resolved permission.
        """

        engine = PermissionEngine()
        rec = _key(policy_name="developer", policy_override={"rate_limit": 42})
        perm = engine.resolve(rec, CHAT_EP)
        assert perm.allowed is True
        assert perm.rate_limit == 42

    def test_override_can_restrict_types(self) -> None:
        """
        An override that explicitly sets allowed_types narrows access.
        """

        engine = PermissionEngine()
        rec = _key(
            policy_name="developer",
            policy_override={"allowed_types": ["chat"]},
        )
        assert engine.resolve(rec, CHAT_EP).allowed is True
        assert engine.resolve(rec, EMBED_EP).allowed is False

    def test_override_with_unknown_base_policy_still_denies(self) -> None:
        """
        An override cannot grant types the base policy does not have.
        """

        engine = PermissionEngine()
        rec = _key(policy_name="no-such-policy", policy_override={"rate_limit": 10})
        assert engine.resolve(rec, CHAT_EP).allowed is False
