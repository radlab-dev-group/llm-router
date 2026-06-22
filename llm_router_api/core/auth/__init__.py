"""
Authentication module for llm-router.

All submodules are loaded lazily at runtime to avoid side effects during
package import (e.g. the startup validation in ``constants.py``).

Import from submodules directly when possible::

    from llm_router_api.core.auth.middleware import install_auth_middleware
    from llm_router_api.core.auth.key_generator import KeyGenerator

Or use this package's lazy ``__getattr__`` loader::

    from llm_router_api.core.auth import KeyGenerator  # loads key_generator on demand
"""

import importlib
import sys  # noqa: E402
from types import ModuleType  # noqa: E402
from typing import Any  # noqa: E402

__all__ = [
    "install_auth_middleware",
    "create_key_store",
    "RedisRateLimiter",
    "PermissionEngine",
    "ApiKeyRecord",
    "EndpointPolicy",
    "EndpointPermission",
    "KeyGenerator",
    "AuthAuditorBridge",
    "AuthResult",
]

# Mapping of exported names to (submodule, attr_name).
_EXPORTS: dict[str, tuple[str, str]] = {
    "install_auth_middleware": (".middleware", "install_auth_middleware"),
    "create_key_store":        (".key_store",       "create_key_store"),
    "RedisRateLimiter":        (".rate_limiter",    "RedisRateLimiter"),
    "PermissionEngine":        (".policies.engine",  "PermissionEngine"),
    "ApiKeyRecord":            (".policies.model",   "ApiKeyRecord"),
    "EndpointPolicy":          (".policies.model",   "EndpointPolicy"),
    "EndpointPermission":      (".policies.model",   "EndpointPermission"),
    "KeyGenerator":            (".key_generator",    "KeyGenerator"),
    "AuthAuditorBridge":       (".audit",            "AuthAuditorBridge"),
    "AuthResult":              (".errors",           "AuthResult"),
}

_MOD_CACHE: dict[str, ModuleType] = {}


def __getattr__(name: str) -> Any:
    submodule_path, attr_name = _EXPORTS.get(name, (None, None))
    if submodule_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    mod = _MOD_CACHE.get(submodule_path)
    if mod is None:
        mod = importlib.import_module(submodule_path, package=__name__)
        _MOD_CACHE[submodule_path] = mod

    val = getattr(mod, attr_name)
    # Cache the actual symbol so future lookups bypass __getattr__ entirely.
    object.__setattr__(sys.modules[__name__], name, val)  # type: ignore[arg-type]
    return val
