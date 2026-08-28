"""
Pure message-list normalisation helpers.

These functions normalise a chat ``messages`` list so that it is compatible
with any service that expects a ``system`` → ``user`` → ``assistant``
alternating sequence.  They are deliberately written as module‑level pure
functions (no endpoint state) so they can be unit‑tested in isolation and
reused by :class:`llm_router_api.endpoints.endpoint_i.EndpointWithHttpRequestI`
via thin delegating methods.

Behaviour contract (unchanged from the previous in‑class implementation):

* consecutive messages of the same role are merged (contents joined);
* every ``system`` message is folded into a single leading ``system`` message;
* an empty ``user`` placeholder is prepended when the dialogue starts with an
  ``assistant`` (or non‑user) turn;
* an empty ``user`` placeholder is appended when the dialogue ends with an
  ``assistant`` turn (a chat completion request must end with a ``user``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def merge_message_contents(content_a: Any, content_b: Any) -> Any:
    """
    Join the contents of two messages into a single content value.

    String contents are joined with a blank line.  List contents
    (multimodal payloads) are concatenated into one list.
    """
    if content_a is None:
        return content_b
    if content_b is None:
        return content_a
    if isinstance(content_a, list) or isinstance(content_b, list):
        parts_a = (
            content_a
            if isinstance(content_a, list)
            else [{"type": "text", "text": content_a}]
        )
        parts_b = (
            content_b
            if isinstance(content_b, list)
            else [{"type": "text", "text": content_b}]
        )
        return parts_a + parts_b
    text_a = str(content_a)
    text_b = str(content_b)
    if not text_a:
        return text_b
    if not text_b:
        return text_a
    return f"{text_a}\n\n{text_b}"


def messages_need_fix(messages: List[Any]) -> bool:
    """
    Check whether the *messages* list requires normalisation.

    The check scans the list in a single pass (with early exit) and detects
    any condition that :func:`build_alternating_messages` would change:

    * more than one ``system`` message (they are folded into one);
    * a ``system`` message which is not the very first entry (moved to front);
    * two consecutive dialogue messages with the same role (they are merged);
    * a dialogue that does not start with a ``user`` turn (a placeholder is
      prepended);
    * a dialogue that ends with an ``assistant`` turn (a placeholder is
      appended).

    Non‑message entries (non‑dicts or dicts without a ``role``) act as
    separators in the dialogue sequence, exactly as during the rebuild.

    Parameters
    ----------
    messages:
        The raw ``messages`` list extracted from the request payload.

    Returns
    -------
    bool
        ``True`` when the list has to be rebuilt, ``False`` when it already
        follows the expected ``system`` → alternating dialogue pattern and can
        be returned untouched.
    """
    first = messages[0]
    last = messages[-1]

    system_count = 0
    prev_role: Optional[str] = None
    for msg in messages:
        role = msg.get("role") if isinstance(msg, dict) else None
        if role == "system":
            system_count += 1
            if system_count > 1:
                return True
            continue
        if role is None:
            # Non‑message entries break the dialogue sequence.
            prev_role = None
            continue
        if role == prev_role:
            return True
        prev_role = role

    # A single system message is allowed, but only as the first entry.
    if system_count == 1 and not (
        isinstance(first, dict) and first.get("role") == "system"
    ):
        return True

    # Without a leading system, the dialogue must start with a user turn.
    if (
        system_count == 0
        and isinstance(first, dict)
        and first.get("role") not in (None, "user")
    ):
        return True

    # The dialogue must not end with an assistant turn.
    if isinstance(last, dict) and last.get("role") == "assistant":
        return True

    return False


def build_alternating_messages(messages: List[Any]) -> List[Dict]:
    """
    Rebuild the *messages* list so that it starts with a single folded
    ``system`` message followed by a strictly alternating dialogue.

    The rebuild is performed in a single pass: ``system`` messages are folded
    into one at the front, consecutive dialogue messages of the same role are
    merged, and empty ``user`` placeholders are inserted so that the dialogue
    starts and ends with a ``user`` turn.

    Every message dict that may later be mutated is shallow‑copied first, so
    the caller's original dicts are never touched.  This matters because the
    retry path re‑runs this normalisation on the same payload and in‑place
    mutations would merge contents twice.

    Parameters
    ----------
    messages:
        The raw ``messages`` list extracted from the request payload.

    Returns
    -------
    List[Dict]
        A new, correctly ordered list of messages.
    """
    new_messages: List[Dict[str, Any]] = []
    system_msg: Optional[Dict[str, Any]] = None
    last: Any = None  # last appended dialogue entry (always a fresh copy)

    for msg in messages:
        role = msg.get("role") if isinstance(msg, dict) else None
        if role == "system":
            if system_msg is None:
                system_msg = dict(msg)
            else:
                system_msg["content"] = merge_message_contents(
                    system_msg.get("content"), msg.get("content")
                )
        elif (
            role is not None
            and last is not None
            and isinstance(last, dict)
            and last.get("role") == role
        ):
            last["content"] = merge_message_contents(
                last.get("content"), msg.get("content")
            )
        else:
            new_messages.append(dict(msg) if isinstance(msg, dict) else msg)
            last = new_messages[-1]

    if system_msg is not None:
        new_messages.insert(0, system_msg)

    # The dialogue must start with a user message.
    first = new_messages[0]
    if isinstance(first, dict) and first.get("role") not in (
        None,
        "system",
        "user",
    ):
        new_messages.insert(0, {"role": "user", "content": ""})

    # The dialogue must end with a user message.
    last_entry = new_messages[-1]
    if isinstance(last_entry, dict) and last_entry.get("role") == "assistant":
        new_messages.append({"role": "user", "content": ""})

    return new_messages


def ensure_alternating_roles(
    params: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Normalise a ``messages`` payload for compatibility with any service that
    expects a ``system`` → ``user`` → ``assistant`` alternating sequence.

    Consecutive messages of the same role are merged into a single message
    (their contents are joined), e.g.::

        [system, system, user, user, user]
            -> [system, user]

    Additional fixes applied:

    * every ``system`` message is moved to the front and folded into a single
      ``system`` message;
    * if the first dialogue message is an ``assistant`` one, an empty ``user``
      placeholder is prepended;
    * if the last message is an ``assistant`` one, an empty ``user``
      placeholder is appended (a chat completion request must end with a
      ``user`` turn).

    Well‑formed payloads are detected in a single pass and returned untouched
    (no copying), so the common case costs almost nothing.

    Parameters
    ----------
    params:
        Request payload possibly containing a ``messages`` list.

    Returns
    -------
    Dict
        The possibly‑modified payload with a correctly ordered ``messages``
        list.
    """
    if not params or "messages" not in params:
        return params

    messages = params["messages"]
    if not isinstance(messages, list) or len(messages) <= 1:
        return params

    if messages_need_fix(messages):
        params["messages"] = build_alternating_messages(messages)
    return params


__all__ = [
    "ensure_alternating_roles",
    "messages_need_fix",
    "build_alternating_messages",
    "merge_message_contents",
]
