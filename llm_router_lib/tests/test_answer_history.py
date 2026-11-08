"""Both client styles preserve chronological answer history on the wire."""

import asyncio
from unittest import mock

import pytest

from llm_router_lib import AsyncLLMRouterClient, LLMRouterClient
from llm_router_lib.data_models import GenerativeAnswerModel
from llm_router_lib.services.utils import (
    GenerativeAnswerService,
    GenerativeAnswerWithCitationsService,
)

HISTORY = [{"user": "When?", "assistant": "In 2000 [7]."}]
DOCUMENTS = [
    {
        "n": 7,
        "text_str": "Founded in 2000.",
        "document_name": "acme.pdf",
        "page_number": 2,
    }
]


@pytest.mark.parametrize(
    "method, service",
    [
        ("generative_answer", GenerativeAnswerService),
        ("generative_answer_with_citations", GenerativeAnswerWithCitationsService),
    ],
)
@pytest.mark.parametrize("prebuilt", [False, True])
def test_sync_answer_history(method, service, prebuilt):
    values = dict(
        question_str="Use a table.",
        enumerated_documents=DOCUMENTS,
        system_prompt_with_enumerated_documents=True,
        historical_messages=HISTORY,
    )
    kwargs = (
        {"payload": GenerativeAnswerModel(model_name="m", **values)}
        if prebuilt
        else values
    )
    client = LLMRouterClient(api="http://router.test", default_model="m")
    with mock.patch.object(
        service, "call_post", return_value={"response": "2000 [7]."}
    ) as call:
        getattr(client, method)(**kwargs)
    assert call.call_args.args[0]["historical_messages"] == HISTORY
    assert call.call_args.args[0]["enumerated_documents"] == DOCUMENTS


@pytest.mark.parametrize(
    "method, service",
    [
        ("generative_answer", GenerativeAnswerService),
        ("generative_answer_with_citations", GenerativeAnswerWithCitationsService),
    ],
)
@pytest.mark.parametrize("prebuilt", [False, True])
def test_async_answer_history(method, service, prebuilt):
    async def run():
        values = dict(
            question_str="Use a table.",
            enumerated_documents=DOCUMENTS,
            system_prompt_with_enumerated_documents=True,
            historical_messages=HISTORY,
        )
        kwargs = (
            {"payload": GenerativeAnswerModel(model_name="m", **values)}
            if prebuilt
            else values
        )
        async with AsyncLLMRouterClient(
            api="http://router.test", default_model="m"
        ) as client:
            with mock.patch.object(
                client, "_post_json", return_value={"response": "2000 [7]."}
            ) as call:
                await getattr(client, method)(**kwargs)
            assert call.call_args.args[0] is service
            assert call.call_args.args[1]["historical_messages"] == HISTORY
            assert call.call_args.args[1]["enumerated_documents"] == DOCUMENTS

    asyncio.run(run())
