"""
Pre-defined builtin policies.

These are loaded at import time and serve as the default set of roles
when the user creates a key without specifying a policy.

Custom policies (created with ``llm-router auth policy create``) are
persisted to a JSON file (default: ``~/.llm-router/configs/auth/
custom-policies.json``, overridable with the
``LLM_ROUTER_AUTH_CUSTOM_POLICIES_FILE`` environment variable) and are
transparently visible to both the CLI and the server engine through
:func:`get_builtin_policy` / :func:`list_builtin_policies`.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from llm_router_api.core.auth.policies.model import (
    EndpointPermission,
    EndpointPolicy,
)

#: Policy fields stored as tuples that may round-trip as JSON lists.
#: (path, mtime, policies) — invalidated whenever the file changes.
_cache: Optional[Tuple[Path, float, Dict[str, EndpointPolicy]]] = None
_cache_lock = threading.Lock()


def custom_policies_file() -> Path:
    """
    Return the file that stores custom policies (env override supported).
    """
    env_path = os.environ.get("LLM_ROUTER_AUTH_CUSTOM_POLICIES_FILE", "").strip()
    if env_path:
        return Path(env_path).expanduser()
    return (
        Path.home() / ".llm-router" / "configs" / "auth" / "custom-policies.json"
    )


def _normalize_policy(data: Dict) -> EndpointPolicy:
    """Rebuild an :class:`EndpointPolicy` from a plain JSON-style dict."""
    if not isinstance(data, dict):
        raise ValueError("policy definition must be a JSON object")
    permissions = data.get("permissions") or {}
    if not isinstance(permissions, dict):
        raise ValueError("'permissions' must be an object")
    perm_map = {
        key: EndpointPermission(**(perm if isinstance(perm, dict) else {}))
        for key, perm in permissions.items()
    }
    policy = EndpointPolicy(
        can_access=bool(data.get("can_access", False)),
        allowed_types=tuple(data.get("allowed_types") or ()),
        permissions=perm_map,
        rate_limit=int(data.get("rate_limit", 60)),
        ip_whitelist=tuple(data.get("ip_whitelist") or ()),
        model_whitelist=tuple(data.get("model_whitelist") or ()),
        budget_monthly_tokens=data.get("budget_monthly_tokens"),
        budget_tokens_used=int(data.get("budget_tokens_used", 0)),
        is_active=bool(data.get("is_active", True)),
        metadata=dict(data.get("metadata") or {}),
    )
    return policy

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
    Return names of all builtin policies (including persisted custom ones).
    """

    names = list(_builtin_policies.keys())
    for name in load_custom_policies():
        if name not in names:
            names.append(name)
    return names


def get_builtin_policy(name: str) -> Optional[EndpointPolicy]:
    """
    Return a builtin policy by name, falling back to the persisted custom
    policies, or ``None`` when the name is unknown.
    """

    policy = _builtin_policies.get(name)
    if policy is not None:
        return policy
    return load_custom_policies().get(name)


def register_policy(name: str, policy: EndpointPolicy) -> None:
    """
    Register a custom policy for the lifetime of this process.

    For policies that must survive CLI/server restarts use
    :func:`save_policy` instead (or in addition).
    """

    _builtin_policies[name] = policy


def load_custom_policies() -> Dict[str, EndpointPolicy]:
    """
    Load the persisted custom policies (cached until the file changes).

    Missing or unreadable files yield an empty mapping — a broken policy
    file must never take the auth engine down.
    """
    global _cache
    path = custom_policies_file()
    try:
        stat = path.stat()
    except OSError:
        with _cache_lock:
            if _cache is not None and _cache[0] == path:
                return _cache[2]
            _cache = (path, -1.0, {})
        return {}

    with _cache_lock:
        if _cache is not None and _cache[0] == path and _cache[1] == stat.st_mtime:
            return _cache[2]

        policies: Dict[str, EndpointPolicy] = {}
        try:
            raw = json.loads(path.read_bytes())
            if isinstance(raw, dict):
                for name, data in raw.items():
                    try:
                        policies[name] = _normalize_policy(data)
                    except (TypeError, ValueError) as exc:
                        import logging

                        logging.getLogger(__name__).warning(
                            "Skipping invalid custom policy %r in %s: %s",
                            name,
                            path,
                            exc,
                        )
        except (OSError, json.JSONDecodeError) as exc:
            import logging

            logging.getLogger(__name__).warning(
                "Could not load custom policies from %s: %s", path, exc
            )

        _cache = (path, stat.st_mtime, policies)
        return policies


def save_policy(name: str, policy: EndpointPolicy) -> Path:
    """
    Persist *policy* under *name* (merging into the existing file) and
    register it in-process.  Returns the file path written.
    """
    path = custom_policies_file()
    path.parent.mkdir(parents=True, exist_ok=True)

    data: Dict[str, object] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_bytes())
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}

    data[name] = asdict(policy)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    # Refresh the cache so this process sees the new policy immediately.
    global _cache
    with _cache_lock:
        _cache = None
    _builtin_policies[name] = policy
    return path
