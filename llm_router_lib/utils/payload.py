"""
Shared payload construction for the router clients.

Both the synchronous :class:`~llm_router_lib.client.LLMRouterClient` and the
asynchronous :class:`~llm_router_lib.async_client.AsyncLLMRouterClient` accept
every endpoint method in two equivalent ways:

1. a ready‑made Pydantic request model passed as ``payload``, or
2. named domain keyword arguments (``texts`` / ``user_last_statement`` / …,
   plus ``model`` and optional generation options) from which the request
   model is built on the fly.

The single source of truth for this contract lives in
:func:`build_payload` so that the two clients can never drift apart.
Raw ``dict`` payloads are rejected (construct the Pydantic model explicitly),
and a call with neither a payload nor enough arguments raises
:class:`~llm_router_lib.exceptions.NoArgsAndNoPayloadError`.
"""

from typing import Any, Dict, Optional, Type

from pydantic import BaseModel, ValidationError

from llm_router_lib.exceptions import NoArgsAndNoPayloadError


def build_payload(
    *,
    model_cls: Optional[Type[BaseModel]],
    payload_arg: object,
    **extra: object,
) -> Dict[str, Any]:
    """
    Normalise a payload argument to the ``dict`` sent over the wire.

    Handles the three supported input shapes:

    1. **Pydantic model instance** – serialised via ``model_dump()``.
    2. **Dict** – rejected with :class:`TypeError` (raw‑dict payloads were
       removed in favour of explicit Pydantic models).
    3. **``None``** – constructed from the *extra* keyword arguments using
       the provided *model_cls*; :class:`NoArgsAndNoPayloadError` is
       raised when the arguments are missing or fail model validation
       (e.g. a required field is absent).

    Keyword values explicitly set to ``None`` are dropped so that the
    Pydantic model's own defaults apply.

    Parameters
    ----------
    model_cls : Optional[Type[BaseModel]]
        Pydantic model class used to build the payload from named arguments
        (``None`` for endpoints that do not accept a built payload).
    payload_arg : object
        The ``payload`` argument supplied by the caller.
    **extra : object
        Named domain arguments (``model_name``, ``texts``, …) used only when
        ``payload_arg`` is ``None``.

    Returns
    -------
    Dict[str, Any]
        The JSON‑serialisable request payload.

    Raises
    ------
    TypeError
        If ``payload_arg`` is a raw ``dict``.
    NoArgsAndNoPayloadError
        If ``payload_arg`` is ``None`` and no valid payload could be built
        from the named arguments.
    """
    if isinstance(payload_arg, BaseModel):
        return payload_arg.model_dump()

    if isinstance(payload_arg, dict):
        raise TypeError(
            "Passing a raw dict as `payload` is no longer supported. "
            "Instantiate the matching Pydantic request model explicitly "
            "(e.g. `<RequestModel>(**payload)`) and pass that instance, "
            "or use the named keyword arguments instead."
        )

    # payload_arg is None — build the request model from named arguments.
    if model_cls is None:
        raise NoArgsAndNoPayloadError("No payload and no arguments were passed!")

    # Drop explicit Nones so optional fields fall back to model defaults.
    fields = {key: value for key, value in extra.items() if value is not None}
    if not fields:
        raise NoArgsAndNoPayloadError("No payload and no arguments were passed!")

    try:
        return model_cls(**fields).model_dump()
    except ValidationError as exc:
        raise NoArgsAndNoPayloadError(
            "No valid payload could be built from the given arguments "
            f"({exc.error_count()} validation problem(s)); pass a complete "
            "payload model instance or all required named arguments."
        ) from exc
