"""
Integration tests for the per‑text (``call_for_each_user_msg=True``) flow.

Guards the end‑to‑end contract of the ``texts`` utility endpoints
(``polarity_3c``, ``translate``, ``simplify_text``, ``generate_questions``):

* ``prepare_payload`` builds **one ``user`` message per source text**;
* ``run_ep`` must **not** merge those consecutive user messages (the role
  normalizer only applies to conversation endpoints);
* the HTTP executor issues **one call per source text**;
* the final ``response`` is paired **per text**.

This pins the behaviour that regressed in production: the role normalizer
in ``run_ep`` used to merge ``[user, user, …]`` into a single message, so
all of these endpoints silently returned **one merged result** instead of
one result per text.

All HTTP traffic is faked at ``_call_post_with_payload``; the real
``call_http_request`` → ``_call_for_each_user_message`` path runs.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest  # noqa: E402

from llm_router_api.endpoints.builtin.builtin_utils import (  # noqa: E402
    GenerateQuestions,
    Polarity3c,
    SimplifyText,
    Translate,
)
from llm_router_api.endpoints.endpoint_i import (
    EndpointWithHttpRequestI,
)  # noqa: E402
from typing import List

T1 = "Ile lat ma córka która widzi, że nie ma jeszcze 15 lat?"
T2 = "Hehehehehe nie wiem o co Ci chodzi ale chodzi Ci dobrze"


class _FakeResponse:
    """Minimal ``requests.Response`` stand‑in for the per‑text flow."""

    def __init__(self, text: str):
        self._body = {"choices": [{"message": {"content": text}}]}

    def json(self):
        return self._body

    @property
    def ok(self):
        return True

    def raise_for_status(self):
        return None


def _fake_provider():
    return SimpleNamespace(
        name="test-model",
        id="prov-1",
        api_type="openai",
        api_host="http://test.local",
        model_path=None,
        api_token=None,
        tool_calling=False,
    )


def _make_ep(cls, response_text_for):
    """
    Build an endpoint wired to the real dispatch path, faking only the
    model resolution, router metrics and the raw HTTP send.
    """
    ep = cls(logger_file_name=None, prompt_handler=None, model_handler=None)
    ep._get_router_metrics = lambda: None
    ep.get_model_provider = mock.Mock(return_value=_fake_provider())

    sent = []

    def fake_post(
        ep_url,
        params,
        return_raw_response=False,
        headers=None,
        api_model_provider=None,
    ):
        users = [
            m
            for m in params["messages"]
            if isinstance(m, dict) and m.get("role") == "user"
        ]
        # per‑text dispatch: exactly one user message per call
        assert len(users) == 1, f"expected 1 user msg per call, got {users}"
        content = users[0]["content"]
        sent.append(content)
        return _FakeResponse(response_text_for(content))

    ep._http_executor._call_post_with_payload = fake_post
    return ep, sent


class TestPerTextEndToEnd:
    """2 source texts → 2 model calls → 2 paired results (per text)."""

    @pytest.mark.parametrize(
        ("cls", "req_payload"),
        [
            (Polarity3c, {"model_name": "m", "texts": [T1, T2]}),
            (Translate, {"model_name": "m", "texts": [T1, T2]}),
            (SimplifyText, {"model_name": "m", "texts": [T1, T2]}),
            (
                GenerateQuestions,
                {"model_name": "m", "texts": [T1, T2], "number_of_questions": 1},
            ),
        ],
        ids=["polarity_3c", "translate", "simplify_text", "generate_questions"],
    )
    def test_two_texts_produce_two_paired_results(self, cls, req_payload):
        ep, sent = _make_ep(
            cls, response_text_for=lambda c: "positive" if c == T1 else "negative"
        )
        out = ep.run_ep(dict(req_payload))

        # one HTTP call per source text, in input order, unmerged
        assert sent == [T1, T2]

        # results are per text (in input order)
        assert len(out["response"]) == 2
        if cls is SimplifyText:
            # simplify returns a flat list of per-text results (strings)
            assert out["response"] == ["positive", "negative"]
        else:
            source_texts = [
                entry.get("original", entry.get("text")) for entry in out["response"]
            ]
            assert source_texts == [T1, T2]

    def test_polarity_result_shape(self):
        ep, sent = _make_ep(
            Polarity3c,
            response_text_for=lambda c: "positive" if c == T1 else "negative",
        )
        out = ep.run_ep({"model_name": "m", "texts": [T1, T2]})
        assert out["response"][0]["original"] == T1
        assert out["response"][0]["polarity"] == "positive"
        assert out["response"][1]["original"] == T2
        assert out["response"][1]["polarity"] == "negative"


class _MergingChatEndpoint(EndpointWithHttpRequestI):
    """
    A conversation‑style endpoint (``call_for_each_user_msg=False``) used to
    assert that the role normalizer still merges consecutive user messages
    for endpoints that are **not** per‑text.
    """

    def __init__(self):
        super().__init__(
            ep_name="dummy_chat",
            api_types=["builtin"],
            call_for_each_user_msg=False,
        )
        self.REQUIRED_ARGS = ["messages"]
        self.SYSTEM_PROMPT_NAME = None

    def prepare_payload(self, params):
        return {"messages": list(params["messages"])}


class TestNonPerTextStillNormalized:
    def test_consecutive_users_still_merged_for_chat_endpoints(self):
        ep = _MergingChatEndpoint()
        ep._get_router_metrics = lambda: None
        ep.get_model_provider = mock.Mock(return_value=_fake_provider())

        sent = []

        def fake_post(
            ep_url,
            params,
            return_raw_response=False,
            headers=None,
            api_model_provider=None,
        ):
            sent.append(params["messages"])
            resp = _FakeResponse("ok")
            if return_raw_response:
                return resp
            return ep.return_http_response(
                response=resp, api_model_provider=api_model_provider
            )

        ep._http_executor._call_post_with_payload = fake_post

        out = ep.run_ep(
            {
                "messages": [
                    {"role": "user", "content": T1},
                    {"role": "user", "content": T2},
                ]
            }
        )

        # exactly one HTTP call, with the two user messages merged
        assert len(sent) == 1
        assert sent[0] == [{"role": "user", "content": f"{T1}\n\n{T2}"}]
        # and the (single) response is returned as JSON body
        assert out == {"choices": [{"message": {"content": "ok"}}]}
