"""
Data models for the auth layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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
    allowed_models : tuple[str, ...] | None
        Model whitelist (``None`` = all models).
    requires_guardrail : bool
        Whether guardrail checks must be enforced (even if policy says "allow").
    requires_masking : bool
        Whether masking must be enforced.
    rate_limit : int | None
        Per-endpoint rate limit in requests per minute (``None`` = use global default).
    """

    method: str = "ANY"
    allowed: bool = False
    allowed_models: tuple[str, ...] | None = None
    requires_guardrail: bool = True
    requires_masking: bool = False
    rate_limit: int | None = None

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
        Whether the key has *any* access at all.
    permissions : dict[str, EndpointPermission]
        Mapping of endpoint_key → permission.
    rate_limit : int
        Requests per minute (``0`` = unlimited).
    ip_whitelist : tuple[str, ...] | None
        CIDR/IP whitelist (``None`` = no restriction).
    model_whitelist : tuple[str, ...] | None
        Global model whitelist (``None`` = all).
    budget_monthly_tokens : int | None
        Monthly token budget in tokens (``None`` = no budget).
    budget_tokens_used : int
        Tokens used this period (synced from Redis).
    is_active : bool
        Whether the policy itself is active.
    metadata : dict
        Arbitrary metadata (team, cost_center, …).
    """

    can_access: bool = False
    permissions: dict[str, EndpointPermission] = field(default_factory=dict)
    rate_limit: int = 60
    ip_whitelist: tuple[str, ...] | None = None
    model_whitelist: tuple[str, ...] | None = None
    budget_monthly_tokens: int | None = None
    budget_tokens_used: int = 0
    is_active: bool = True
    metadata: dict = field(default_factory=dict)

    def get_permission(
        self, endpoint_key: str, method: str = "POST"
    ) -> EndpointPermission:
        """Return the permission for a specific endpoint and method.

        If ``can_access`` is True and there are no explicit per-endpoint
        restrictions (``permissions`` dict), return an allow-all permission.
        Otherwise look up the exact endpoint_key in ``permissions`` — if it
        is absent, deny (the policy has *some* endpoint-level rules and this
        one wasn't listed).
        """
        if not self.can_access:
            return EndpointPermission(method=method, allowed=False)

        # When can_access=True but no per-endpoint map exists → allow everything
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
    policy_override : dict | None
        Inline policy override (takes precedence over the named policy).
    created_at : float
        Unix timestamp of key creation.
    expires_at : float | None
        Expiry timestamp (``None`` = no expiry).
    last_used_at : float | None
        Last successful authentication time.
    is_active : bool
        Whether the key is currently valid.
    rotate_at : float | None
        Scheduled rotation time (for planned rotation).
    grace_until : float | None
        Keys are valid until this time even after rotation.
    """

    key_id: str
    key_hash: str
    key_prefix: str
    policy_name: str
    policy_override: dict | None = None
    created_at: float = field(default_factory=lambda: __import__("time").time())
    expires_at: float | None = None
    last_used_at: float | None = None
    is_active: bool = True
    rotate_at: float | None = None
    grace_until: float | None = None
