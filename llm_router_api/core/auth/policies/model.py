"""
Data models for the auth layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class EndpointPermission:
    """
    What a given API key may do on a specific endpoint.

    Attributes
    ----------
    method : str
        Allowed HTTP method(s) — ``"GET"``, ``"POST"``, ``"*"``, or ``"ANY"``.
    allowed : bool
        Whether this endpoint is accessible at all.
    allowed_models : Optional[Tuple[str, ...]]
        Model whitelist (``None`` = all models).
    requires_guardrail : bool
        Whether guardrail checks must be enforced (even if policy says "allow").
    requires_masking : bool
        Whether masking must be enforced.
    rate_limit : Optional[int]
        Per-endpoint rate limit in requests per minute (``None`` = use global default).
    """

    method: str = "ANY"
    allowed: bool = False
    allowed_models: Optional[Tuple[str, ...]] = None
    requires_guardrail: bool = True
    requires_masking: bool = False
    rate_limit: Optional[int] = None

    def __post_init__(self) -> None:
        if self.allowed and self.allowed_models:
            object.__setattr__(
                self,
                "allowed_models",
                tuple(str(m).lower() for m in self.allowed_models),
            )


@dataclass
class EndpointPolicy:
    """
    Full policy for an API key — mapping of endpoint → permission.

    Attributes
    ----------
    can_access : bool
        Master switch — whether the key has *any* access at all.
    allowed_types : Optional[Tuple[str, ...]]
        Set of permission **types** the key is granted (e.g. ``"chat"``,
        ``"embedding"``, ``"anthropic"``, ``"ollama"``, ``"builtin"``).
        This is the **default-deny** gate: an endpoint is reachable only if
        its required type (see the engine's endpoint→type map) is present
        here.  ``None``/empty grants *no* types (deny everything) — there is
        no implicit allow-all.
    permissions : Dict[str, EndpointPermission]
        Optional per-endpoint refinements (model whitelists, guardrail flags).
        An empty map imposes no endpoint-level restriction *beyond* the type
        gate; a non-empty map requires the endpoint to be listed there.
    rate_limit : int
        Requests per minute (``0`` = unlimited).
    ip_whitelist : Optional[Tuple[str, ...]]
        CIDR/IP whitelist (``None`` = no restriction).
    model_whitelist : Optional[Tuple[str, ...]]
        Global model whitelist (``None`` = all).
    budget_monthly_tokens : Optional[int]
        Monthly token budget in tokens (``None`` = no budget).
    budget_tokens_used : int
        Tokens used this period (synced from Redis).
    is_active : bool
        Whether the policy itself is active.
    metadata : Dict
        Arbitrary metadata (team, cost_center, …).
    """

    can_access: bool = False
    allowed_types: Optional[Tuple[str, ...]] = None
    permissions: Dict[str, EndpointPermission] = field(default_factory=dict)
    rate_limit: int = 60
    ip_whitelist: Optional[Tuple[str, ...]] = None
    model_whitelist: Optional[Tuple[str, ...]] = None
    budget_monthly_tokens: Optional[int] = None
    budget_tokens_used: int = 0
    is_active: bool = True
    metadata: Dict = field(default_factory=dict)

    def grants_type(self, required_type: str) -> bool:
        """
        Return True if *required_type* (e.g. ``"chat"``) is in the granted set.

        Default-deny: an ``allowed_types`` of ``None`` or empty grants nothing.
        """
        return required_type in (self.allowed_types or ())

    def get_permission(
        self, endpoint_key: str, method: str = "POST"
    ) -> EndpointPermission:
        """
        Return the **endpoint-level** permission for a specific endpoint.

        This is a refinement on top of the type-level default-deny gate
        (handled by :meth:`grants_type` / the engine):

        * ``can_access`` False → deny.
        * no per-endpoint map → allow (no endpoint-level restriction).
        * a per-endpoint map exists but this endpoint is absent → deny.
        """
        if not self.can_access:
            return EndpointPermission(method=method, allowed=False)

        if not self.permissions:
            return EndpointPermission(
                method=method,
                allowed=True,
                requires_guardrail=False,
                requires_masking=False,
            )

        perm = self.permissions.get(endpoint_key)
        if perm is None:
            return EndpointPermission(method=method, allowed=False)
        return perm


@dataclass
class ApiKeyRecord:
    """
    Represents an API key stored in the key store (Vault, Redis, Memory).

    Attributes
    ----------
    key_id : str
        Unique identifier for this key.
    key_hash : str
        bcrypt hash of the plaintext key — *never* stored in plaintext.
    key_prefix : str
        First 7 characters of the plaintext key (for logs only).
    policy_name : str
        Name of the default policy to apply.
    policy_override : Optional[dict]
        Inline policy override (takes precedence over the named policy).
    created_at : float
        Unix timestamp of key creation.
    expires_at : Optional[float]
        Expiry timestamp (``None`` = no expiry).
    last_used_at : Optional[float]
        Last successful authentication time.
    is_active : bool
        Whether the key is currently valid.
    rotate_at : Optional[float]
        Scheduled rotation time (for planned rotation).
    grace_until : Optional[float]
        Keys are valid until this time even after rotation.
    """

    key_id: str
    key_hash: str
    key_prefix: str
    policy_name: str
    policy_override: Optional[dict] = None
    created_at: float = field(default_factory=lambda: __import__("time").time())
    expires_at: Optional[float] = None
    last_used_at: Optional[float] = None
    is_active: bool = True
    rotate_at: Optional[float] = None
    grace_until: Optional[float] = None
