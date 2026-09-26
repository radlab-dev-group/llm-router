"""
Per‑request record of the providers that were already tried.

A single request may be dispatched several times: the HTTP dispatcher retries
on another provider when the current one answers with an error, and
``ModelHandler`` moves on to the ``fallback_model`` chain once every provider
of the requested model failed.  Both decisions need the same piece of state —
the set of provider ``id``\\ s already used by *this* request — which is
carried in the ``options`` dictionary that travels with every re‑run.

The state is stored as a tuple under :data:`ATTEMPTED_PROVIDERS_KEY`, and
helpers always return a **new** options dictionary, so re‑running a request
never mutates the options of the attempt that is being retried.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set

ATTEMPTED_PROVIDERS_KEY = "__attempted_providers"


def provider_id(provider: Any) -> Optional[str]:
    """Return the identifier of *provider* (``ApiModel`` or config dict)."""
    if provider is None:
        return None
    pid = getattr(provider, "id", None)
    if pid is None and isinstance(provider, dict):
        pid = provider.get("id")
    return str(pid) if pid else None


def attempted_provider_ids(options: Optional[Dict[str, Any]]) -> Set[str]:
    """
    Return the provider ids already used by the current request.

    Parameters
    ----------
    options : Optional[Dict[str, Any]]
        Request options, may be ``None``.

    Returns
    -------
    Set[str]
        Provider ids marked with :func:`with_attempted_provider`; empty when
        nothing was tried yet (a request starts with an empty set).
    """
    if not options:
        return set()
    value = options.get(ATTEMPTED_PROVIDERS_KEY) or ()
    try:
        return {str(item) for item in value}
    except TypeError:  # pragma: no cover - defensive (non-iterable value)
        return set()


def with_attempted_provider(
    options: Optional[Dict[str, Any]], provider: Any
) -> Dict[str, Any]:
    """
    Return a copy of *options* marking *provider* as tried.

    Parameters
    ----------
    options : Optional[Dict[str, Any]]
        Options of the attempt that failed; ``None`` starts a fresh mapping.
    provider : Any
        The provider (``ApiModel`` or provider config dict) that failed.

    Returns
    -------
    Dict[str, Any]
        New options dictionary; unchanged content apart from the attempt
        record.  A provider without an ``id`` yields a plain copy.
    """
    new_options: Dict[str, Any] = dict(options) if options else {}
    pid = provider_id(provider)
    if not pid:
        return new_options

    tried = tuple(new_options.get(ATTEMPTED_PROVIDERS_KEY) or ())
    if pid not in tried:
        new_options[ATTEMPTED_PROVIDERS_KEY] = tried + (pid,)
    return new_options
