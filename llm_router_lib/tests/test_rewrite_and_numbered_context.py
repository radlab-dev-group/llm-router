"""Sync/async client parity for query rewriting and numbered context."""

import asyncio
import json
from unittest import mock

import httpx
import pytest

from llm_router_lib import LLMRouterClient, AsyncLLMRouterClient
from llm_router_lib.data_models import (
    GenerativeAnswerModel,
    GenerativeAnswerResponse,
    RewriteQueryModel,
    RewriteQueryResponse,
)
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
from llm_router_lib.services.utils import (
    RewriteQueryService,
    GenerativeAnswerService,
    GenerativeAnswerWithCitationsService,
)

TURNS = [{"user": "Who founded Acme?", "assistant": "Ada."}]
DOCS = [
    {
        "n": 7,
        "text_str": "Founded in 2000.",
        "document_name": "acme",
        "document_id": "d",
    }
]


def test_sync_rewrite_named_and_payload_contract():
    client = LLMRouterClient(api="http://router.test", default_model="default")
    with mock.patch.object(
        RewriteQueryService,
        "call_post",
        return_value={
            "rewritten_query": "When was Acme founded?",
            "generation_time": 0.1,
        },
    ) as call:
        result = client.rewrite_query(
            user_last_statement="When?",
            historical_messages=TURNS,
            model="override",
            lang="en",
        )
        assert isinstance(result, RewriteQueryResponse)
        assert result.rewritten_query == "When was Acme founded?"
        assert result.generation_time == 0.1
        sent = call.call_args.args[0]
        assert sent["model_name"] == "override"
        assert sent["language"] == "en"
        assert sent["historical_messages"] == TURNS
        payload = RewriteQueryModel(
            model_name="payload", user_last_statement="What?"
        )
        client.rewrite_query(payload=payload)
        assert call.call_args.args[0] == payload.model_dump()
        client.rewrite_query(user_last_statement="What?")
        assert call.call_args.args[0]["model_name"] == "default"
    with pytest.raises(TypeError):
        client.rewrite_query(payload={})
    with pytest.raises(NoArgsAndNoPayloadError):
        client.rewrite_query()


def test_sync_numbered_context():
    client = LLMRouterClient(api="http://router.test", default_model="m")
    with mock.patch.object(
        GenerativeAnswerService,
        "call_post",
        return_value={"response": "In 2000 [7].", "citations": DOCS},
    ) as call:
        result = client.generative_answer(
            question_str="When?",
            enumerated_documents=DOCS,
            system_prompt_with_enumerated_documents=True,
            system_prompt="Be brief.",
        )
    assert call.call_args.args[0]["enumerated_documents"] == DOCS
    assert call.call_args.args[0]["system_prompt"] == "Be brief."
    assert result.citations[0].n == 7
    assert result.citations[0].document_id == "d"


def test_sync_dedicated_citations_named_and_payload_contract():
    client = LLMRouterClient(api="http://router.test", default_model="default")
    with mock.patch.object(
        GenerativeAnswerWithCitationsService,
        "call_post",
        return_value={"response": "In 2000 [7].", "citations": DOCS},
    ) as call:
        result = client.generative_answer_with_citations(
            question_str="When?",
            enumerated_documents=DOCS,
            model="override",
            system_prompt="Be brief.",
        )
        assert isinstance(result, GenerativeAnswerResponse)
        assert result.citations[0].n == 7
        assert call.call_args.args[0]["model_name"] == "override"
        assert call.call_args.args[0]["system_prompt"] == "Be brief."
        assert (
            call.call_args.args[0]["system_prompt_with_enumerated_documents"] is True
        )
        payload = GenerativeAnswerModel(
            model_name="payload",
            question_str="When?",
            enumerated_documents=DOCS,
            system_prompt_with_enumerated_documents=True,
        )
        client.generative_answer_with_citations(payload=payload, model="ignored")
        assert call.call_args.args[0] == payload.model_dump()
        client.generative_answer_with_citations(
            question_str="When?",
            enumerated_documents=DOCS,
            system_prompt_with_enumerated_documents=False,
        )
        assert call.call_args.args[0]["model_name"] == "default"
        assert (
            call.call_args.args[0]["system_prompt_with_enumerated_documents"] is True
        )
    with pytest.raises(TypeError):
        client.generative_answer_with_citations(payload={})
    with pytest.raises(NoArgsAndNoPayloadError):
        client.generative_answer_with_citations(
            question_str="When?", texts=["legacy"]
        )


def test_async_dedicated_citations_wire_contract():
    captured = []

    def handler(request):
        captured.append((request.url.path, json.loads(request.content)))
        return httpx.Response(
            200, json={"response": "In 2000 [7].", "citations": DOCS}
        )

    async def run():
        async with AsyncLLMRouterClient(
            api="http://router.test",
            default_model="m",
            transport=httpx.MockTransport(handler),
        ) as client:
            result = await client.generative_answer_with_citations(
                question_str="When?",
                enumerated_documents=DOCS,
                system_prompt="Be brief.",
            )
            assert isinstance(result, GenerativeAnswerResponse)
            assert result.citations[0].document_id == "d"
            payload = GenerativeAnswerModel(
                model_name="payload",
                question_str="When?",
                enumerated_documents=DOCS,
                system_prompt_with_enumerated_documents=True,
            )
            await client.generative_answer_with_citations(payload=payload)
            assert captured[-1][1] == payload.model_dump()
            with pytest.raises(TypeError):
                await client.generative_answer_with_citations(payload={})
            with pytest.raises(NoArgsAndNoPayloadError):
                await client.generative_answer_with_citations(
                    question_str="q", texts=["legacy"]
                )

    asyncio.run(run())
    assert captured[0][0] == "/api/generative_answer_with_citations"
    assert captured[0][1]["system_prompt_with_enumerated_documents"] is True
    assert captured[0][1]["system_prompt"] == "Be brief."
    assert captured[0][1]["enumerated_documents"] == DOCS


def test_async_rewrite_and_numbered_context_wire_contract():
    captured = []

    def handler(request):
        captured.append((request.url.path, json.loads(request.content)))
        if request.url.path.endswith("rewrite_query"):
            return httpx.Response(
                200,
                json={
                    "rewritten_query": "When was Acme founded?",
                    "generation_time": 0.2,
                },
            )
        return httpx.Response(
            200, json={"response": "In 2000 [7].", "citations": DOCS}
        )

    async def run():
        async with AsyncLLMRouterClient(
            api="http://router.test",
            default_model="m",
            transport=httpx.MockTransport(handler),
        ) as client:
            result = await client.rewrite_query(
                user_last_statement="When?", historical_messages=TURNS, lang="en"
            )
            assert isinstance(result, RewriteQueryResponse)
            assert result.rewritten_query == "When was Acme founded?"
            assert result.generation_time == 0.2
            result = await client.generative_answer(
                question_str="When?",
                enumerated_documents=DOCS,
                system_prompt_with_enumerated_documents=True,
            )
            assert result.citations[0].n == 7
            with pytest.raises(TypeError):
                await client.rewrite_query(payload={})
            with pytest.raises(NoArgsAndNoPayloadError):
                await client.rewrite_query()

    asyncio.run(run())
    assert captured[0][0] == "/api/rewrite_query"
    assert captured[0][1]["historical_messages"] == TURNS
    assert captured[0][1]["language"] == "en"
    assert captured[1][0] == "/api/generative_answer"
    assert captured[1][1]["enumerated_documents"] == DOCS
