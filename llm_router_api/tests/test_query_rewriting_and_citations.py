"""Non-streaming query rewriting and explicit context numbering contracts."""

import contextvars
import os
from pathlib import Path
from unittest import mock

os.environ.setdefault("LLM_ROUTER_MINIMUM", "1")
os.environ.setdefault("LLM_ROUTER_AUTH_ENABLED", "0")

import pytest
from flask import Flask
from pydantic import ValidationError

from llm_router_api.core.auth.policies.engine import _ENDPOINT_PERMISSION_MAP
from llm_router_api.endpoints.builtin.builtin_utils import (
    GenerativeAnswer,
    GenerativeAnswerWithCitations,
    RewriteQuery,
)
from llm_router_api.register.register import FlaskEndpointRegistrar
from llm_router_lib.data_models import GenerativeAnswerModel, RewriteQueryModel

DOCUMENTS = [
    {
        "n": 8,
        "text_str": "First fragment",
        "document_name": "same.pdf",
        "text_id": "a",
    },
    {
        "n": 3,
        "text_str": "Second fragment",
        "document_name": "same.pdf",
        "text_id": "b",
        "page_number": 4,
    },
]


def numbered_params(**kwargs):
    return dict(
        model_name="m",
        question_str="What happened?",
        enumerated_documents=DOCUMENTS,
        system_prompt_with_enumerated_documents=True,
        **kwargs,
    )


def response(text):
    result = mock.Mock()
    result.json.return_value = {"choices": [{"message": {"content": text}}]}
    return result


@pytest.fixture
def resource_prompt_handler():
    root = Path(__file__).resolve().parents[2] / "resources" / "prompts"
    handler = mock.Mock()
    handler.get_prompt.side_effect = lambda name: (
        root / f"{name}.prompt"
    ).read_text()
    return handler


@pytest.mark.parametrize("language", ["pl", "en"])
@pytest.mark.parametrize(
    "endpoint_cls, prompt_file",
    [
        (RewriteQuery, "rewrite-query"),
        (GenerativeAnswerWithCitations, "answer-from-context-with-citations"),
    ],
)
def test_dedicated_endpoints_resolve_prompt_resources(
    language, endpoint_cls, prompt_file, resource_prompt_handler
):
    ep = endpoint_cls(prompt_handler=resource_prompt_handler)
    params = (
        {"model_name": "m", "user_last_statement": "When?", "language": language}
        if endpoint_cls is RewriteQuery
        else numbered_params(
            language=language,
            system_prompt="Use a table.",
            question_prompt="Be brief.",
        )
    )
    payload = ep.prepare_payload(params)
    assert not payload.get("prompt_str_force")
    name, prompt = ep._resolve_prompt_name(
        params=payload,
        map_prompt=payload.get("map_prompt"),
        prompt_str_force=payload.get("prompt_str_force"),
        prompt_str_postfix=payload.get("prompt_str_postfix"),
    )
    assert name == f"builtin/system/{language}/{prompt_file}"
    resource_prompt_handler.get_prompt.assert_called_once_with(name)
    assert prompt and "##" not in prompt
    if endpoint_cls is GenerativeAnswerWithCitations:
        assert "[n]" in prompt
        assert "What happened?" in prompt
        assert prompt.endswith("Use a table.\n\nBe brief.")


@pytest.mark.parametrize("language", ["pl", "en"])
def test_legacy_numbered_mode_uses_citation_resource(
    language, resource_prompt_handler
):
    ep = GenerativeAnswer(prompt_handler=resource_prompt_handler)
    payload = ep.prepare_payload(
        numbered_params(language=language, system_prompt="Use a table.")
    )
    _, prompt = ep._resolve_prompt_name(
        params=payload,
        map_prompt=payload["map_prompt"],
        prompt_str_force=payload["prompt_str_force"],
        prompt_str_postfix=payload["prompt_str_postfix"],
    )
    resource_prompt_handler.get_prompt.assert_called_once_with(
        f"builtin/system/{language}/answer-from-context-with-citations"
    )
    assert "[n]" in prompt
    assert "What happened?" in prompt
    assert "##QUESTION_STR##" not in prompt
    assert prompt.endswith("Use a table.")


def test_rewrite_payload_and_response():
    ep = RewriteQuery()
    payload = ep.prepare_payload(
        {
            "model_name": "m",
            "language": "en",
            "historical_messages": [
                {"user": "Who founded Acme?", "assistant": "Ada."}
            ],
            "user_last_statement": "When?",
        }
    )
    assert payload["model"] == "m"
    assert payload["messages"][-1] == {"role": "user", "content": "When?"}
    assert payload["messages"][:-1] == [
        {"role": "user", "content": "Who founded Acme?"},
        {"role": "assistant", "content": "Ada."},
    ]
    assert not payload.get("prompt_str_force")
    result = ep.prepare_response_function(response("  When did Ada found Acme?  "))
    assert result["rewritten_query"] == "When did Ada found Acme?"
    assert "generation_time" in result
    assert _ENDPOINT_PERMISSION_MAP["post:/api/rewrite_query"] == "builtin"


@pytest.mark.parametrize(
    "turn",
    [{"user": "x"}, {"role": "user", "content": "x"}, {"user": 1, "assistant": "a"}],
)
def test_rewrite_invalid_turn(turn):
    with pytest.raises(ValidationError):
        RewriteQueryModel(
            model_name="m", user_last_statement="q", historical_messages=[turn]
        )


def test_numbered_context_preserves_order_metadata_and_custom_prompt():
    ep = GenerativeAnswer()
    payload = ep.prepare_payload(
        numbered_params(
            system_prompt="Answer briefly.", question_prompt="Be precise."
        )
    )
    assert payload["messages"][0]["content"] == (
        "[8] Document name: same.pdf\nDocument context: First fragment\n\n"
        "[3] Document name: same.pdf; Page number: 4\nDocument context: Second fragment"
    )
    assert payload["prompt_str_force"] is None
    assert payload["map_prompt"] == {"##QUESTION_STR##": "What happened?"}
    assert payload["prompt_str_postfix"] == "Answer briefly.\n\nBe precise."
    assert "enumerated_documents" not in payload
    result = ep.prepare_response_function(response("First [8], then second [3]."))
    assert [c["n"] for c in result["citations"]] == [8, 3]
    assert [c["text_id"] for c in result["citations"]] == ["a", "b"]
    assert result["citations"][1]["page_number"] == 4


def test_unknown_citation_is_rejected():
    ep = GenerativeAnswer()
    ep.prepare_payload(numbered_params())
    with pytest.raises(ValueError, match="99"):
        ep.prepare_response_function(response("Unsupported [99]."))


@pytest.mark.parametrize("enabled", [None, False, True])
def test_dedicated_citation_endpoint_forces_numbering(
    enabled, resource_prompt_handler
):
    ep = GenerativeAnswerWithCitations(prompt_handler=resource_prompt_handler)
    params = numbered_params(system_prompt="Keep my custom instructions.")
    if enabled is None:
        params.pop("system_prompt_with_enumerated_documents")
    else:
        params["system_prompt_with_enumerated_documents"] = enabled
    payload = ep.prepare_payload(params)
    assert payload["prompt_str_force"] is None
    _, prompt = ep._resolve_prompt_name(
        params=payload,
        map_prompt=payload["map_prompt"],
        prompt_str_postfix=payload["prompt_str_postfix"],
    )
    assert prompt.endswith("Keep my custom instructions.")
    assert "[n]" in prompt
    assert payload["messages"][0]["content"].index("[8]") < payload["messages"][0][
        "content"
    ].index("[3]")
    assert (
        ep.prepare_response_function(response("Facts [8] and [3]."))["citations"]
        == DOCUMENTS
    )
    with pytest.raises(ValueError, match="99"):
        ep.prepare_response_function(response("Unknown [99]."))
    assert (
        "system_prompt_with_enumerated_documents" not in params
        or params["system_prompt_with_enumerated_documents"] is enabled
    )


def test_dedicated_citation_route_validation_generation_and_auth():
    app = Flask(__name__)
    ep = GenerativeAnswerWithCitations()
    FlaskEndpointRegistrar(app=app).register_endpoint(ep)
    client = app.test_client()
    route = "/api/generative_answer_with_citations"
    assert _ENDPOINT_PERMISSION_MAP[f"post:{route}"] == "builtin"
    assert (
        client.post(
            route, json={"model_name": "m", "question_str": "q", "texts": ["legacy"]}
        ).status_code
        == 400
    )
    assert (
        client.post(
            route,
            json={
                "model_name": "m",
                "question_str": "q",
                "enumerated_documents": [],
            },
        ).status_code
        == 400
    )

    def generate(**kwargs):
        assert "[8]" in kwargs["params"]["messages"][0]["content"]
        return ep.prepare_response_function(response("Generated answer [8]."))

    params = numbered_params(system_prompt="Be brief.")
    params.pop("system_prompt_with_enumerated_documents")
    with (
        mock.patch.object(ep, "_dispatch_non_streaming", side_effect=generate),
        mock.patch.object(
            ep, "_resolve_provider", return_value=mock.Mock(api_type="openai")
        ),
        mock.patch.object(
            ep,
            "_prepare_params_for_provider",
            side_effect=lambda params, **_: params,
        ),
        mock.patch.object(ep, "_secure_payload", side_effect=lambda params: params),
        mock.patch.object(ep, "_is_request_guardrail_safe", return_value=True),
    ):
        result = client.post(route, json=params)
    assert result.status_code == 200
    assert result.get_json()["response"] == "Generated answer [8]."
    assert result.get_json()["citations"] == DOCUMENTS


def test_citation_context_is_request_local_and_legacy_is_unchanged():
    ep = GenerativeAnswer()
    first, second = contextvars.Context(), contextvars.Context()
    first.run(ep.prepare_payload, numbered_params())
    second.run(
        ep.prepare_payload,
        {"model_name": "m", "question_str": "q", "texts": {"doc": ["legacy"]}},
    )
    assert "citations" not in second.run(
        ep.prepare_response_function, response("Legacy [99]")
    )
    assert [
        c["n"]
        for c in first.run(ep.prepare_response_function, response("Fact [8]"))[
            "citations"
        ]
    ] == [8, 3]


@pytest.mark.parametrize(
    "documents",
    [
        [],
        [DOCUMENTS[0], DOCUMENTS[0]],
        [dict(DOCUMENTS[0], n=0)],
        [dict(DOCUMENTS[0], n="8")],
        [dict(DOCUMENTS[0], text_str=" ")],
        [{"n": 1, "document_name": "missing text"}],
    ],
)
def test_invalid_numbered_documents(documents):
    params = numbered_params()
    params["enumerated_documents"] = documents
    with pytest.raises(ValidationError):
        GenerativeAnswerModel(**params)


def test_ambiguous_context_rejected():
    with pytest.raises(ValidationError):
        GenerativeAnswerModel(**numbered_params(texts=["silently ignored?"]))


def test_api_validation_and_success_routes():
    app = Flask(__name__)
    registrar = FlaskEndpointRegistrar(app=app)
    rewrite, answer = RewriteQuery(), GenerativeAnswer()
    registrar.register_endpoint(rewrite)
    registrar.register_endpoint(answer)
    client = app.test_client()
    assert (
        client.post("/api/rewrite_query", json={"model_name": "m"}).status_code
        == 400
    )
    params = numbered_params()
    params["enumerated_documents"] = [dict(DOCUMENTS[0], n=0)]
    assert client.post("/api/generative_answer", json=params).status_code == 400
    with (
        mock.patch.object(
            rewrite,
            "_dispatch_non_streaming",
            return_value={"rewritten_query": "Standalone?"},
        ),
        mock.patch.object(
            rewrite, "_resolve_provider", return_value=mock.Mock(api_type="openai")
        ),
        mock.patch.object(
            rewrite,
            "_prepare_params_for_provider",
            side_effect=lambda params, **_: params,
        ),
        mock.patch.object(
            rewrite, "_secure_payload", side_effect=lambda params: params
        ),
        mock.patch.object(rewrite, "_is_request_guardrail_safe", return_value=True),
    ):
        result = client.post(
            "/api/rewrite_query",
            json={"model_name": "m", "user_last_statement": "When?"},
        )
    assert result.status_code == 200
    assert result.get_json()["rewritten_query"] == "Standalone?"
