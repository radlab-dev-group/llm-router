"""
Unit tests for the pure helpers in ``llm_router_api.endpoints.message_normalizer``.

Covers:

* ``merge_message_contents`` – None passthrough, string joining, list
  (multimodal) concatenation and mixed list/string wrapping;
* ``messages_need_fix`` – detection of every condition that forces a
  rebuild (and ``False`` for well‑formed lists);
* ``build_alternating_messages`` – system folding, same‑role merging,
  user‑placeholder insertion, non‑dict entries and input non‑mutation;
* ``ensure_alternating_roles`` – fast path (no copy) vs. rebuild path.
"""

from __future__ import annotations

import os

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

from llm_router_api.endpoints import message_normalizer  # noqa: E402


# --------------------------------------------------------------------------- #
# merge_message_contents
# --------------------------------------------------------------------------- #


class TestMergeMessageContents:
    def test_none_first_returns_second(self):
        assert message_normalizer.merge_message_contents(None, "b") == "b"

    def test_none_second_returns_first(self):
        assert message_normalizer.merge_message_contents("a", None) == "a"

    def test_both_none_returns_none(self):
        assert message_normalizer.merge_message_contents(None, None) is None

    def test_strings_joined_with_blank_line(self):
        assert message_normalizer.merge_message_contents("a", "b") == "a\n\nb"

    def test_empty_first_returns_second(self):
        assert message_normalizer.merge_message_contents("", "b") == "b"

    def test_empty_second_returns_first(self):
        assert message_normalizer.merge_message_contents("a", "") == "a"

    def test_lists_are_concatenated(self):
        part_a = [{"type": "text", "text": "a"}]
        part_b = [{"type": "text", "text": "b"}]
        assert (
            message_normalizer.merge_message_contents(part_a, part_b)
            == part_a + part_b
        )

    def test_list_plus_string_wraps_string(self):
        parts = [{"type": "text", "text": "a"}]
        out = message_normalizer.merge_message_contents(parts, "b")
        assert out == parts + [{"type": "text", "text": "b"}]

    def test_string_plus_list_wraps_string(self):
        parts = [{"type": "image_url", "image_url": "x"}]
        out = message_normalizer.merge_message_contents("a", parts)
        assert out == [{"type": "text", "text": "a"}] + parts


# --------------------------------------------------------------------------- #
# messages_need_fix
# --------------------------------------------------------------------------- #


def _msg(role, content="c"):
    return {"role": role, "content": content}


class TestMessagesNeedFix:
    def test_well_formed_dialogue_needs_no_fix(self):
        assert (
            message_normalizer.messages_need_fix(
                [_msg("user"), _msg("assistant"), _msg("user")]
            )
            is False
        )

    def test_system_then_alternating_is_ok(self):
        assert (
            message_normalizer.messages_need_fix(
                [_msg("system"), _msg("user"), _msg("assistant"), _msg("user")]
            )
            is False
        )

    def test_ending_with_assistant_needs_fix(self):
        assert (
            message_normalizer.messages_need_fix([_msg("user"), _msg("assistant")])
            is True
        )

    def test_starting_with_assistant_needs_fix(self):
        assert (
            message_normalizer.messages_need_fix([_msg("assistant"), _msg("user")])
            is True
        )

    def test_two_system_messages_need_fix(self):
        assert (
            message_normalizer.messages_need_fix(
                [_msg("system"), _msg("system"), _msg("user"), _msg("user")]
            )
            is True
        )

    def test_system_not_first_needs_fix(self):
        assert (
            message_normalizer.messages_need_fix(
                [_msg("user"), _msg("system"), _msg("user")]
            )
            is True
        )

    def test_consecutive_same_role_needs_fix(self):
        assert (
            message_normalizer.messages_need_fix(
                [_msg("user"), _msg("user"), _msg("assistant"), _msg("user")]
            )
            is True
        )

    def test_non_message_entry_breaks_dialogue_sequence(self):
        # ``"sep"`` acts as a separator, so the two ``user`` turns are not
        # consecutive dialogue messages.
        assert (
            message_normalizer.messages_need_fix([_msg("user"), "sep", _msg("user")])
            is False
        )

    def test_dict_without_role_is_a_separator(self):
        assert (
            message_normalizer.messages_need_fix(
                [_msg("user"), {"foo": 1}, _msg("user")]
            )
            is False
        )


# --------------------------------------------------------------------------- #
# build_alternating_messages
# --------------------------------------------------------------------------- #


class TestBuildAlternatingMessages:
    def test_systems_folded_to_single_leading_message(self):
        out = message_normalizer.build_alternating_messages(
            [
                _msg("system", "s1"),
                _msg("system", "s2"),
                _msg("user"),
                _msg("assistant"),
                _msg("user"),
            ]
        )
        assert len(out) == 4
        assert out[0]["role"] == "system"
        assert out[0]["content"] == "s1\n\ns2"
        assert [m["role"] for m in out[1:]] == ["user", "assistant", "user"]

    def test_consecutive_same_role_merged(self):
        out = message_normalizer.build_alternating_messages(
            [_msg("user", "a"), _msg("user", "b"), _msg("assistant"), _msg("user")]
        )
        assert [m["role"] for m in out] == ["user", "assistant", "user"]
        assert out[0]["content"] == "a\n\nb"

    def test_user_placeholder_prepended_for_assistant_start(self):
        out = message_normalizer.build_alternating_messages(
            [_msg("assistant"), _msg("user")]
        )
        assert out[0] == {"role": "user", "content": ""}
        assert [m["role"] for m in out] == ["user", "assistant", "user"]

    def test_user_placeholder_appended_for_assistant_end(self):
        out = message_normalizer.build_alternating_messages(
            [_msg("user"), _msg("assistant")]
        )
        assert out[-1] == {"role": "user", "content": ""}

    def test_single_assistant_gets_both_placeholders(self):
        out = message_normalizer.build_alternating_messages([_msg("assistant")])
        assert out[0] == {"role": "user", "content": ""}
        assert out[1] == _msg("assistant")
        assert out[2] == {"role": "user", "content": ""}

    def test_non_dict_entries_pass_through(self):
        raw = [_msg("user"), "sep", _msg("assistant"), _msg("user")]
        out = message_normalizer.build_alternating_messages(raw)
        assert out[1] == "sep"

    def test_original_dicts_not_mutated(self):
        sys_msg = _msg("system", "s1")
        user1 = _msg("user", "a")
        user2 = _msg("user", "b")
        out = message_normalizer.build_alternating_messages(
            [sys_msg, user1, user2, _msg("assistant"), _msg("user")]
        )
        # originals keep their exact contents
        assert sys_msg["content"] == "s1"
        assert user1["content"] == "a"
        assert user2["content"] == "b"
        # the merged result lives in fresh dicts
        assert out[0]["content"] == "s1"
        assert out[1]["content"] == "a\n\nb"
        assert out[1] is not user1

    def test_well_formed_list_is_rebuilt_with_same_shape(self):
        raw = [_msg("user"), _msg("assistant"), _msg("user")]
        out = message_normalizer.build_alternating_messages(raw)
        assert [m["role"] for m in out] == ["user", "assistant", "user"]


# --------------------------------------------------------------------------- #
# ensure_alternating_roles
# --------------------------------------------------------------------------- #


class TestEnsureAlternatingRoles:
    def test_none_params_return_none(self):
        assert message_normalizer.ensure_alternating_roles(None) is None

    def test_params_without_messages_returned_untouched(self):
        params = {"model": "x"}
        assert message_normalizer.ensure_alternating_roles(params) is params

    def test_non_list_messages_returned_untouched(self):
        params = {"messages": "oops"}
        assert message_normalizer.ensure_alternating_roles(params) is params

    def test_single_message_returned_untouched(self):
        params = {"messages": [_msg("assistant")]}
        assert message_normalizer.ensure_alternating_roles(params) is params

    def test_well_formed_payload_returned_without_copy(self):
        messages = [_msg("user"), _msg("assistant"), _msg("user")]
        params = {"messages": messages}
        out = message_normalizer.ensure_alternating_roles(params)
        assert out is params
        assert out["messages"] is messages

    def test_malformed_payload_rebuilt_in_place(self):
        messages = [_msg("assistant"), _msg("user")]
        params = {"messages": messages}
        out = message_normalizer.ensure_alternating_roles(params)
        assert out is params
        assert out["messages"] is not messages
        assert [m["role"] for m in out["messages"]] == [
            "user",
            "assistant",
            "user",
        ]
        # the original list object is not mutated
        assert [m["role"] for m in messages] == ["assistant", "user"]

    def test_original_message_dicts_untouched_after_rebuild(self):
        first = _msg("assistant", "a")
        second = _msg("user", "u")
        params = {"messages": [first, second]}
        message_normalizer.ensure_alternating_roles(params)
        assert first["content"] == "a"
        assert second["content"] == "u"
