"""
Pre-defined builtin policies.

These are loaded at import time and serve as the default set of roles
when the user creates a key without specifying a policy.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from llm_router_api.core.auth.policies.model import EndpointPolicy

# Every permission type that can appear in the engine's endpoint→type map.
_ALL_TYPES = ("chat", "embedding", "anthropic", "ollama", "builtin")

# Default-deny: a policy grants access only to the types listed in
# ``allowed_types``.  Full-access roles explicitly enumerate every type;
# single-purpose roles grant only their own type.
_builtin_policies: Dict[str, EndpointPolicy] = {
    "developer": EndpointPolicy(can_access=True, allowed_types=_ALL_TYPES),
    "admin": EndpointPolicy(
        can_access=True, allowed_types=_ALL_TYPES, metadata={"level": "admin"}
    ),
    "chat": EndpointPolicy(can_access=True, allowed_types=("chat",)),
    "embedding": EndpointPolicy(can_access=True, allowed_types=("embedding",)),
    "anthropic": EndpointPolicy(can_access=True, allowed_types=("anthropic",)),
    "ollama": EndpointPolicy(can_access=True, allowed_types=("ollama",)),
    "builtin": EndpointPolicy(can_access=True, allowed_types=("builtin",)),
}


def list_builtin_policies() -> List[str]:
    """
    Return names of all builtin policies.
    """

    return list(_builtin_policies.keys())


def get_builtin_policy(name: str) -> Optional[EndpointPolicy]:
    """
    Return a builtin policy by name, or ``None``.
    """

    return _builtin_policies.get(name)


def register_policy(name: str, policy: EndpointPolicy) -> None:
    """
    Register a custom policy (for CLI ``auth policy create``).
    """

    _builtin_policies[name] = policy
