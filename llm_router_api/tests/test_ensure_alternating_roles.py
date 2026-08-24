"""
Tests for ``EndpointWithHttpRequestI._ensure_alternating_roles``.

Covers the fast path (well‑formed payloads pass through unchanged and
uncopied), message merging, placeholder insertion, input non‑mutation
(retry‑path safety) and equivalence with the original reference
algorithm on a large set of random payloads.
"""

from __future__ import annotations

import copy
import json
import os
import random

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from llm_router_api.endpoints.endpoint_i import EndpointWithHttpRequestI


EP = EndpointWithHttpRequestI


def normalize(messages):
    """
    Run the method under test on a fresh payload and return the resulting
    ``messages`` list.
    """
    result = EP._ensure_alternating_roles({"messages": messages})
    return result["messages"]


# ---------------------------------------------------------------------------
# Reference implementation (pre‑optimisation algorithm) used as an oracle
# ---------------------------------------------------------------------------
def _reference_ensure_alternating_roles(params):
    """
    Verbatim copy of the original implementation, kept as an oracle for
    the equivalence tests.
    """
    if not params or "messages" not in params:
        return params

    messages = params["messages"]
    if not isinstance(messages, list) or len(messages) <= 1:
        return params

    def is_msg(obj):
        return isinstance(obj, dict) and obj.get("role") is not None

    system_msgs = [m for m in messages if is_msg(m) and m["role"] == "system"]
    dialogue = [m for m in messages if not (is_msg(m) and m["role"] == "system")]

    new_messages = []
    if system_msgs:
        merged = dict(system_msgs[0])
        for extra in system_msgs[1:]:
            merged["content"] = EP._merge_message_contents(
                merged.get("content"), extra.get("content")
            )
        new_messages.append(merged)

    for msg in dialogue:
        if (
            new_messages
            and is_msg(msg)
            and is_msg(new_messages[-1])
            and new_messages[-1]["role"] == msg["role"]
        ):
            new_messages[-1]["content"] = EP._merge_message_contents(
                new_messages[-1].get("content"), msg.get("content")
            )
            continue
        new_messages.append(dict(msg) if is_msg(msg) else msg)

    first = new_messages[0] if new_messages else None
    if is_msg(first) and first["role"] not in ("system", "user"):
        new_messages.insert(0, {"role": "user", "content": ""})

    last = new_messages[-1] if new_messages else None
    if is_msg(last) and last["role"] == "assistant":
        new_messages.append({"role": "user", "content": ""})

    params["messages"] = new_messages
    return params


# ---------------------------------------------------------------------------
# Early returns
# ---------------------------------------------------------------------------


class TestEarlyReturns:
    """
    The method must short‑circuit on payloads without a normalisable list.
    """

    def test_none_params(self):
        assert EP._ensure_alternating_roles(None) is None

    def test_params_without_messages(self):
        params = {"model": "x"}
        assert EP._ensure_alternating_roles(params) is params

    def test_empty_messages_list(self):
        params = {"messages": []}
        assert EP._ensure_alternating_roles(params) is params

    def test_single_message_is_not_touched(self):
        msgs = [{"role": "assistant", "content": "hi"}]
        result = EP._ensure_alternating_roles({"messages": msgs})
        assert result["messages"] is msgs

    def test_messages_not_a_list(self):
        params = {"messages": "just a string"}
        assert EP._ensure_alternating_roles(params) is params


# ---------------------------------------------------------------------------
# Fast path – well‑formed payloads are returned untouched and uncopied
# ---------------------------------------------------------------------------


class TestFastPathReturn:
    """
    Well‑formed payloads must be returned as the *same* list object with
    the *same* message dicts (no copying at all).
    """

    def test_well_formed_with_system(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
        ]
        result = EP._ensure_alternating_roles({"messages": msgs})
        assert result["messages"] is msgs
        assert result["messages"][0] is msgs[0]
        assert result["messages"][1] is msgs[1]

    def test_well_formed_without_system(self):
        msgs = [
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
        ]
        result = EP._ensure_alternating_roles({"messages": msgs})
        assert result["messages"] is msgs

    def test_well_formed_with_none_content(self):
        msgs = [
            {"role": "user", "content": None},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
        ]
        result = EP._ensure_alternating_roles({"messages": msgs})
        assert result["messages"] is msgs

    def test_dict_without_role_is_a_separator(self):
        msgs = [
            {"content": "no role"},
            {"role": "user", "content": "u1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "u2"},
        ]
        result = EP._ensure_alternating_roles({"messages": msgs})
        assert result["messages"] is msgs
        assert len(result["messages"]) == 4


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


class TestMerging:
    """
    Consecutive same‑role dialogue messages are merged; every system
    message is folded into a single one at the front.
    """

    def test_consecutive_users_merged(self):
        msgs = [
            {"role": "user", "content": "A"},
            {"role": "user", "content": "B"},
            {"role": "assistant", "content": "C"},
        ]
        result = normalize(msgs)
        assert len(result) == 3
        assert result[0] == {"role": "user", "content": "A\n\nB"}
        assert result[1] == {"role": "assistant", "content": "C"}

    def test_consecutive_assistants_merged(self):
        result = normalize(
            [
                {"role": "user", "content": "A"},
                {"role": "assistant", "content": "B"},
                {"role": "assistant", "content": "C"},
            ]
        )
        assert len(result) == 3
        assert result[1]["content"] == "B\n\nC"
        assert result[2] == {"role": "user", "content": ""}

    def test_multiple_systems_folded_to_front(self):
        result = normalize(
            [
                {"role": "system", "content": "s1"},
                {"role": "system", "content": "s2"},
                {"role": "user", "content": "u"},
            ]
        )
        assert len(result) == 2
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "s1\n\ns2"
        assert result[1] == {"role": "user", "content": "u"}

    def test_system_in_middle_moved_and_users_merged_across_it(self):
        result = normalize(
            [
                {"role": "user", "content": "A"},
                {"role": "system", "content": "s"},
                {"role": "user", "content": "B"},
            ]
        )
        assert result == [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "A\n\nB"},
        ]

    def test_system_between_same_roles_is_no_separator(self):
        # systems are removed before the dialogue is merged, so they do
        # not separate two same‑role messages
        result = normalize(
            [
                {"role": "assistant", "content": "A"},
                {"role": "system", "content": "s"},
                {"role": "assistant", "content": "B"},
            ]
        )
        assert result[0] == {"role": "system", "content": "s"}
        assert result[1]["content"] == "A\n\nB"

    def test_non_message_entry_is_a_separator(self):
        msgs = [
            {"role": "user", "content": "A"},
            "plain string entry",
            {"role": "user", "content": "B"},
        ]
        result = normalize(msgs)
        assert len(result) == 3
        assert result[1] == "plain string entry"

    def test_none_contents_merged(self):
        assert normalize(
            [
                {"role": "user", "content": None},
                {"role": "user", "content": "B"},
            ]
        ) == [{"role": "user", "content": "B"}]
        assert normalize(
            [
                {"role": "user", "content": "A"},
                {"role": "user", "content": None},
            ]
        ) == [{"role": "user", "content": "A"}]

    def test_multimodal_contents_merged(self):
        result = normalize(
            [
                {"role": "user", "content": [{"type": "text", "text": "A"}]},
                {"role": "user", "content": "B"},
            ]
        )
        assert result == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "A"},
                    {"type": "text", "text": "B"},
                ],
            }
        ]


# ---------------------------------------------------------------------------
# Placeholders
# ---------------------------------------------------------------------------


class TestPlaceholders:
    """
    The dialogue must start with a ``user`` turn and end with a ``user``
    turn; empty placeholders are inserted when missing.
    """

    def test_assistant_first_gets_user_prepended(self):
        result = normalize(
            [
                {"role": "assistant", "content": "A"},
                {"role": "user", "content": "B"},
            ]
        )
        assert result[0] == {"role": "user", "content": ""}
        assert result[1] == {"role": "assistant", "content": "A"}
        assert result[2] == {"role": "user", "content": "B"}

    def test_assistant_last_gets_user_appended(self):
        result = normalize(
            [
                {"role": "user", "content": "A"},
                {"role": "assistant", "content": "B"},
            ]
        )
        assert result[-1] == {"role": "user", "content": ""}

    def test_assistant_both_ends(self):
        result = normalize(
            [
                {"role": "assistant", "content": "A"},
                {"role": "user", "content": "B"},
                {"role": "assistant", "content": "C"},
            ]
        )
        assert result[0] == {"role": "user", "content": ""}
        assert result[-1] == {"role": "user", "content": ""}

    def test_tool_role_also_requires_placeholder(self):
        result = normalize(
            [
                {"role": "tool", "content": "T"},
                {"role": "user", "content": "B"},
            ]
        )
        assert result[0] == {"role": "user", "content": ""}


# ---------------------------------------------------------------------------
# Input non‑mutation (retry‑path safety)
# ---------------------------------------------------------------------------


class TestInputNotMutated:
    """
    The method must never mutate the caller's message dicts – the retry
    path re‑runs the normalisation on the same (shallow‑copied) payload
    and in‑place mutations would merge contents twice.
    """

    def test_input_dicts_not_mutated(self):
        msgs = [
            {"role": "system", "content": "s1"},
            {"role": "system", "content": "s2"},
            {"role": "user", "content": "A"},
            {"role": "user", "content": "B"},
        ]
        snapshot = copy.deepcopy(msgs)
        EP._ensure_alternating_roles({"messages": msgs})
        assert msgs == snapshot

    def test_retry_with_shared_message_dicts_is_stable(self):
        shared = [
            {"role": "user", "content": "A"},
            {"role": "user", "content": "B"},
        ]
        first = EP._ensure_alternating_roles({"messages": shared})
        # the retry path re‑uses the same message objects (shallow copy)
        second = EP._ensure_alternating_roles({"messages": list(shared)})
        assert first["messages"] == second["messages"]
        assert first["messages"][0]["content"] == "A\n\nB"


# ---------------------------------------------------------------------------
# Equivalence with the reference (original) implementation
# ---------------------------------------------------------------------------


class TestEquivalenceWithReference:
    """
    Property test: on a large batch of random payloads the optimised
    implementation must produce exactly the same result as the original
    algorithm.
    """

    def test_random_payloads_match_reference(self):
        rng = random.Random(42)
        roles = ["system", "user", "assistant", "tool"]
        contents = ["a", "bb", "", None, [{"type": "text", "text": "z"}]]

        def random_entry():
            roll = rng.random()
            if roll < 0.08:
                return "raw"
            if roll < 0.16:
                return {"content": "no-role"}
            return {
                "role": rng.choice(roles),
                "content": rng.choice(contents),
            }

        for _ in range(2000):
            msgs = [random_entry() for _ in range(rng.randint(0, 12))]

            new_msgs = normalize(json.loads(json.dumps(msgs)))
            ref_msgs = _reference_ensure_alternating_roles(
                {"messages": json.loads(json.dumps(msgs))}
            )["messages"]

            assert new_msgs == ref_msgs, f"mismatch for payload: {msgs}"
