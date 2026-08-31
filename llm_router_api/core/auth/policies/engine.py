"""
Permission engine — resolves a key → policy → endpoint permissions.
"""

from __future__ import annotations

import time

from typing import Any, Dict, Optional

from llm_router_api.core.auth.policies import builtin as builtin_policies
from llm_router_api.core.auth.policies.model import (
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
_ENDPOINT_PERMISSION_MAP: Dict[str, str] = {
    # ── Public endpoints — always accessible, no auth required
    #    (even when LLM_ROUTER_AUTH_ENABLED=true) ──
    "get:/metrics": "_public",  # Prometheus metrics (requires Redis + prometheus flag)
    "get:/health": "_public",  # Router health check (no token)
    # ── Auth endpoints — require valid API key with the
    #    matching permission (only when LLM_ROUTER_AUTH_ENABLED=true) ──
    "get:/": "chat",  # Ollama health endpoint
    "get:/api/ping": "builtin",  # Health‑check
    "get:/api/version": "builtin",  # Router version info
    "get:/api/tags": "chat",  # Ollama model tags (prefix path)
    "get:/models": "chat",  # OpenAI‑compatible models list
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
    "post:/api/polarity_3c": "builtin",
    "post:/api/translate": "builtin",
    "post:/api/simplify_text": "builtin",
    "post:/api/generate_label": "builtin",
    "post:/api/generate_article_from_text": "builtin",
    "post:/api/generate_article_from_texts": "builtin",
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
        self, custom_policies: Optional[Dict[str, EndpointPolicy]] = None
    ) -> None:
        self._custom_policies: Dict[str, EndpointPolicy] = custom_policies or {}

    @staticmethod
    def _normalize(record: Any) -> Any:
        """
        Ensure *record* supports attribute access (works for dicts or ApiKeyRecord).
        """
        if isinstance(record, dict):

            class _AttrDict(dict):
                """
                A dict that also supports ``obj.attr`` access.
                """

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
        model_name: Optional[str] = None,
        client_ip: Optional[str] = None,
        tokens_used: Optional[int] = None,
    ) -> EndpointPermission:
        """
        Return the permission for *key* on *endpoint*.

        Authorization is **default-deny**: an endpoint is reachable only if
        (a) it is known to the endpoint→type map, (b) the key's policy grants
        that endpoint's required permission type, (c) any IP whitelist and
        token budget hold, and (d) the endpoint-level policy allows it.

        Parameters
        ----------
        key_record : ApiKeyRecord or Dict
            The authenticated key (object or plain dict — both supported).
        endpoint_key : str
            The normalized endpoint key (e.g. ``"post:/v1/chat/completions"``).
        model_name : Optional[str]
            The model being accessed (used for model whitelist checks).
        client_ip : Optional[str]
            The client IP (used for the policy's ``ip_whitelist``).
        tokens_used : Optional[int]
            Tokens the key has used this period (budget check). Falls back to
            ``policy.budget_tokens_used`` when ``None``.

        Returns
        -------
        EndpointPermission
        """
        record = self._normalize(key_record)
        # Normalise the method case: callers send Flask-style uppercase
        # methods ("POST:/v1/...") while the endpoint map is lowercase.
        method, _, path = endpoint_key.partition(":")
        endpoint_key = f"{method.lower()}:{path}"
        method = method.upper()

        # 1. Public endpoints — always pass
        required_type = _ENDPOINT_PERMISSION_MAP.get(endpoint_key)
        if required_type == "_public":
            return EndpointPermission(
                method=method,
                allowed=True,
                requires_guardrail=False,
                requires_masking=False,
            )

        # 2. Policy
        policy = self._get_policy(record)

        # 3. Master switch + key active + not expired
        if not policy.is_active or not record.is_active:
            return EndpointPermission(method=method, allowed=False)
        if record.expires_at and time.time() > record.expires_at:
            return EndpointPermission(method=method, allowed=False)

        # 4. Default-deny: endpoint must be known AND its type must be granted.
        #    An endpoint absent from the map (required_type is None) is denied.
        if required_type is None or not policy.grants_type(required_type):
            return EndpointPermission(method=method, allowed=False)

        # 5. IP whitelist (default-deny when configured)
        if policy.ip_whitelist and not self._ip_in_whitelist(
            client_ip, policy.ip_whitelist
        ):
            return EndpointPermission(method=method, allowed=False)

        # 6. Monthly token budget (default-deny when set and exceeded)
        if policy.budget_monthly_tokens is not None:
            used = (
                tokens_used if tokens_used is not None else policy.budget_tokens_used
            )
            if used >= policy.budget_monthly_tokens:
                return EndpointPermission(method=method, allowed=False)

        # 7. Endpoint-level refinement (model lists, guardrail/masking flags)
        perm = policy.get_permission(endpoint_key, method=method)
        if not perm.allowed:
            return EndpointPermission(method=method, allowed=False)

        # 8. Model whitelist check (global)
        if policy.model_whitelist and model_name:
            model_lower = model_name.lower()
            if not any(model_lower in w.lower() for w in policy.model_whitelist):
                return EndpointPermission(method=method, allowed=False)

        # 9. Endpoint-specific model whitelist
        if perm.allowed_models and model_name:
            model_lower = model_name.lower()
            if not any(model_lower in w.lower() for w in perm.allowed_models):
                return EndpointPermission(method=method, allowed=False)

        return EndpointPermission(
            method=method,
            allowed=True,
            requires_guardrail=perm.requires_guardrail,
            requires_masking=perm.requires_masking,
            rate_limit=policy.rate_limit if hasattr(policy, "rate_limit") else 60,
        )

    @staticmethod
    def _ip_in_whitelist(client_ip: Optional[str], whitelist) -> bool:
        """
        Return True if *client_ip* is covered by *whitelist* (IPs and/or CIDRs).

        ``client_ip`` must be a valid IP; malformed whitelist entries are
        skipped rather than raising.
        """
        if not client_ip:
            return False
        import ipaddress

        try:
            ip = ipaddress.ip_address(client_ip)
        except ValueError:
            return False
        for entry in whitelist:
            entry = str(entry).strip()
            if not entry:
                continue
            try:
                if "/" in entry:
                    if ip in ipaddress.ip_network(entry, strict=False):
                        return True
                elif ip == ipaddress.ip_address(entry):
                    return True
            except ValueError:
                continue
        return False

    def _get_policy(self, record: Any) -> EndpointPolicy:
        """
        Resolve the policy for a key record (object or dict).
        """

        base = self._named_policy(record)

        # 1. policy_override (partial — e.g. just a rate_limit tweak)
        if record.policy_override:
            policy = self._parse_override(record.policy_override)
            policy.is_active = True
            # Inherit the type grants from the base policy when the override
            # does not explicitly set ``allowed_types``.  Without this, a
            # partial override like ``{"rate_limit": N}`` (written by the CLI
            # ``rate-limit apply``) would grant *no* types and default-deny
            # everything for that key.
            if policy.allowed_types is None:
                policy.allowed_types = base.allowed_types
            return policy

        # 2. Named policy (builtin or custom)
        return base

    def _named_policy(self, record: Any) -> EndpointPolicy:
        """
        Return the named policy for *record*, or a default-deny policy.
        """

        named = record.policy_name
        policy = self._custom_policies.get(named)
        if policy is None:
            policy = builtin_policies.get_builtin_policy(named)
        if policy is None:
            # Default-deny: an unknown policy name grants *nothing*.
            # (Previously this silently fell back to the allow-all
            # "developer" role — a authorization hole.)
            policy = EndpointPolicy(can_access=False)
        return policy

    @staticmethod
    def _parse_override(override: dict) -> EndpointPolicy:
        """
        Parse an inline policy override into an EndpointPolicy.
        """

        perms = {}
        for ep, perms_config in override.get("permissions", {}).items():
            if isinstance(perms_config, EndpointPermission):
                perms[ep] = perms_config
            elif isinstance(perms_config, dict):
                perms[ep] = EndpointPermission(**perms_config)

        allowed_types = override.get("allowed_types")
        if allowed_types is not None:
            allowed_types = tuple(allowed_types)
        return EndpointPolicy(
            can_access=override.get("can_access", True),
            allowed_types=allowed_types,
            permissions=perms,
            rate_limit=override.get("rate_limit", 60),
            is_active=override.get("is_active", True),
            metadata=override.get("metadata", {}),
        )

    def add_custom_policy(self, name: str, policy: EndpointPolicy) -> None:
        """
        Register a custom policy that can be referenced by keys.
        """

        self._custom_policies[name] = policy
