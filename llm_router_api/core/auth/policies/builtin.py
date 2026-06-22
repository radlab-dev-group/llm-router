"""
Pre-defined builtin policies.

These are loaded at import time and serve as the default set of roles
when the user creates a key without specifying a policy.
"""

from __future__ import annotations

from llm_router_api.core.auth.policies.model import EndpointPolicy

_builtin_policies: dict[str, EndpointPolicy] = {
    "developer": EndpointPolicy(can_access=True),
    "admin": EndpointPolicy(can_access=True, metadata={"level": "admin"}),
    "chat": EndpointPolicy(can_access=True),
    "embedding": EndpointPolicy(can_access=True),
    "anthropic": EndpointPolicy(can_access=True),
    "ollama": EndpointPolicy(can_access=True),
    "builtin": EndpointPolicy(can_access=True),
}


def list_builtin_policies() -> list[str]:
    """Return names of all builtin policies."""
    return list(_builtin_policies.keys())


def get_builtin_policy(name: str) -> EndpointPolicy | None:
    """Return a builtin policy by name, or ``None``."""
    return _builtin_policies.get(name)


def register_policy(name: str, policy: EndpointPolicy) -> None:
    """Register a custom policy (for CLI ``auth policy create``)."""
    _builtin_policies[name] = policy
