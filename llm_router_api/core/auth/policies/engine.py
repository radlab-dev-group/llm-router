"""
Permission engine — resolves a key → policy → endpoint permissions.
"""

from __future__ import annotations

import time
from typing import Any

from llm_router_api.core.auth.policies import builtin as builtin_policies
from llm_router_api.core.auth.policies.model import (
    ApiKeyRecord,
    EndpointPermission,
    EndpointPolicy,
)


# -- Endpoint key normalization --------------------------------------
def _endpoint_key(method: str, path: str) -> str:
    """
    Canonical endpoint key for permission lookup.

    Examples:
        ``("POST", "/api/chat/completions")`` → ``"post:/api/chat/completions"``
        ``("GET", "/ping")`` → ``"get:/ping"``
    """
    return f"{method.upper()}:{path}"


# -- Per-endpoint permission mapping -------------------------------
# Maps internal endpoint keys to the policy permission they should use.
# Values of "_public" mean the endpoint bypasses all auth checks (always accessible).
# All other values are the required permission type (e.g. "chat", "embedding").
# NOTE: Auth enforcement only applies when LLM_ROUTER_AUTH_ENABLED=true.
_ENDPOINT_PERMISSION_MAP: dict[str, str] = {
    # ── Public endpoints — always accessible, no auth required (even when LLM_ROUTER_AUTH_ENABLED=true) ──
    "get:/ping": "_public",  # Health‑check
    "get:/version": "_public",  # Router version info
    "get:/": "_public",  # Ollama health endpoint
    "get:/api/tags": "_public",  # Ollama model tags (prefix path)
    "get:/metrics": "_public",  # Prometheus metrics (requires Redis + prometheus flag)
    "get:/models": "_public",  # OpenAI‑compatible models list
    # ── Auth endpoints — require valid API key with the matching permission (only when LLM_ROUTER_AUTH_ENABLED=true) ──
    "get:/v1/models": "chat",  # OpenAI models v1 (not in default public path)
    "get:/api/v0/models": "chat",  # LM Studio models
    "post:/api/chat/completions": "chat",  # OpenAI‑style chat completion (with prefix)
    "post:/v1/chat/completions": "chat",  # vLLM‑like chat completion
    "post:/chat/completions": "chat",  # OpenAI‑style chat completion (alt path)
    "post:/v0/chat/completions": "chat",  # LM Studio chat completion
    "post:/v1/messages": "anthropic",  # Anthropic Messages API (Claude)
    "post:/v1/responses": "chat",  # OpenAI‑like responses v1
    "post:/responses": "chat",  # OpenAI‑like responses (base path)
    "post:/v1/embeddings": "embedding",  # OpenAI‑compatible embeddings v1
    "post:/embeddings": "embedding",  # Standard embeddings (base path)
    "post:/api/embeddings": "embedding",  # Standard embeddings (with prefix)
    "post:/api/embed": "embedding",  # Ollama‑native embeddings
    "post:/api/chat": "ollama",  # Ollama‑style chat completion
    "post:/api/conversation_with_model": "builtin",
    "post:/api/extended_conversation_with_model": "builtin",
    "post:/api/generate_questions": "builtin",
    "post:/api/translate": "builtin",
    "post:/api/simplify_text": "builtin",
    "post:/api/generate_article_from_text": "builtin",
    "post:/api/create_full_article_from_texts": "builtin",
    "post:/api/generative_answer": "builtin",
    "post:/api/fast_text_mask": "builtin",
}


class PermissionEngine:
    """
    Resolve API-key → policy → endpoint permissions.

    The engine reads the key's policy from the key store (or uses
    ``policy_override`` if present) and then checks the per-endpoint
    permission matrix.
    """

    def __init__(
        self, custom_policies: dict[str, EndpointPolicy] | None = None
    ) -> None:
        self._custom_policies: dict[str, EndpointPolicy] = custom_policies or {}

    @staticmethod
    def _normalize(record: Any) -> Any:
        """Ensure *record* supports attribute access (works for dicts or ApiKeyRecord)."""
        if isinstance(record, dict):

            class _AttrDict(dict):
                """A dict that also supports ``obj.attr`` access."""

                def __getattr__(self, attr: str) -> Any:  # noqa: D105
                    val = self.get(attr)
                    if val is None and attr not in self:
                        raise AttributeError(
                            f"{type(self).__name__!r} object has no attribute {attr!r}"
                        )
                    return val

            return _AttrDict(record)
        return record

    def resolve(
        self,
        key_record: Any,
        endpoint_key: str,
        model_name: str | None = None,
    ) -> EndpointPermission:
        """
        Return the permission for *key* on *endpoint*.

        Parameters
        ----------
        key_record : ApiKeyRecord | dict
            The authenticated key (object or plain dict — both supported).
        endpoint_key : str
            The normalized endpoint key (e.g. ``"post:/v1/chat/completions"``).
        model_name : str | None
            The model being accessed (used for model whitelist checks).

        Returns
        -------
        EndpointPermission
        """
        record = self._normalize(key_record)

        # Public endpoints — always pass
        builtin_perm = _ENDPOINT_PERMISSION_MAP.get(endpoint_key)
        if builtin_perm == "_public":
            return EndpointPermission(
                method=endpoint_key.split(":")[0],
                allowed=True,
                requires_guardrail=False,
                requires_masking=False,
            )

        # Fetch policy
        policy = self._get_policy(record)

        # Key is inactive or expired
        if not policy.is_active or not record.is_active:
            return EndpointPermission(
                method=endpoint_key.split(":")[0],
                allowed=False,
            )
        if record.expires_at and time.time() > record.expires_at:
            return EndpointPermission(
                method=endpoint_key.split(":")[0],
                allowed=False,
            )

        # Get the permission type for this endpoint
        perm_type = builtin_perm or "chat"  # default fallback
        perm = policy.get_permission(endpoint_key)

        if not perm.allowed:
            return EndpointPermission(
                method=endpoint_key.split(":")[0],
                allowed=False,
            )

        # Model whitelist check (global)
        if policy.model_whitelist and model_name:
            model_lower = model_name.lower()
            whitelisted = any(
                model_lower in w.lower() for w in policy.model_whitelist
            )
            if not whitelisted:
                return EndpointPermission(
                    method=endpoint_key.split(":")[0],
                    allowed=False,
                )

        # Endpoint-specific model whitelist
        if perm.allowed_models and model_name:
            model_lower = model_name.lower()
            whitelisted = any(model_lower in w.lower() for w in perm.allowed_models)
            if not whitelisted:
                return EndpointPermission(
                    method=endpoint_key.split(":")[0],
                    allowed=False,
                )

        return EndpointPermission(
            method=endpoint_key.split(":")[0],
            allowed=True,
            requires_guardrail=perm.requires_guardrail,
            requires_masking=perm.requires_masking,
        )

    def _get_policy(self, record: Any) -> EndpointPolicy:
        """Resolve the policy for a key record (object or dict)."""
        # 1. policy_override
        if record.policy_override:
            policy = self._parse_override(record.policy_override)
            policy.is_active = True
            return policy

        # 2. Named policy (builtin or custom)
        named = record.policy_name
        policy = self._custom_policies.get(named)
        if policy is None:
            policy = builtin_policies.get_builtin_policy(named)
        if policy is None:
            # Fallback to developer
            policy = builtin_policies.get_builtin_policy("developer")
        return policy

    def _parse_override(self, override: dict) -> EndpointPolicy:
        """Parse an inline policy override into an EndpointPolicy."""
        perms = {}
        for ep, perms_config in override.get("permissions", {}).items():
            if isinstance(perms_config, EndpointPermission):
                perms[ep] = perms_config
            elif isinstance(perms_config, dict):
                perms[ep] = EndpointPermission(**perms_config)

        return EndpointPolicy(
            can_access=override.get("can_access", True),
            permissions=perms,
            rate_limit=override.get("rate_limit", 60),
            is_active=override.get("is_active", True),
            metadata=override.get("metadata", {}),
        )

    def add_custom_policy(self, name: str, policy: EndpointPolicy) -> None:
        """Register a custom policy that can be referenced by keys."""
        self._custom_policies[name] = policy
