"""
Manual end-to-end harness for the :class:`AsyncLLMRouterClient`.

Runs the async client against a live router and prints:

* health / version / models meta responses,
* a non-streaming conversation response,
* a streaming conversation (token by token) and the aggregated text.

Usage (requires a running router and ``httpx``)::

    LLM_API_HOST=http://127.0.0.1:8080 LLM_API_TOKEN=... \
        python -m llm_router_lib.tests.async_llm_router_client
"""

import os
import json
import asyncio

from llm_router_lib import AsyncLLMRouterClient


class Models:
    google_gemma_vllm = "google/gemma-3-12b-it"
    speakleash_bielik_2_3 = "speakleash/Bielik-11B-v2.3-Instruct"


async def main() -> None:
    api_host = os.getenv("LLM_API_HOST", "http://127.0.0.1:8080")
    token = os.getenv("LLM_API_TOKEN", "")

    async with AsyncLLMRouterClient(
        api=api_host, token=token, timeout=180
    ) as client:
        # ---------------------------------------------------------------- #
        # meta endpoints
        # ---------------------------------------------------------------- #
        for label, coro in [
            ("ping", client.ping()),
            ("version", client.version()),
            ("models", client.models()),
        ]:
            result = await coro
            print("--" * 50)
            print(f" =========== {label} =========== ")
            print(
                json.dumps(
                    result.model_dump(), indent=1, ensure_ascii=False
                )
            )

        # ---------------------------------------------------------------- #
        # non-streaming conversation
        # ---------------------------------------------------------------- #
        print("--" * 50)
        print(" =========== conversation (non-streaming) =========== ")
        result = await client.conversation_with_model(
            user_last_statement="Powiedz jedno zdanie o Warszawie.",
            model=Models.google_gemma_vllm,
        )
        print(json.dumps(result.model_dump(), indent=1, ensure_ascii=False))

        # ---------------------------------------------------------------- #
        # streaming conversation
        # ---------------------------------------------------------------- #
        print("--" * 50)
        print(" =========== conversation (streaming) =========== ")
        async for event in client.stream_conversation_with_model(
            user_last_statement="Powiedz jedno zdanie o Krakowie.",
            model=Models.google_gemma_vllm,
        ):
            if event.text:
                print(event.text, end="", flush=True)
            if event.done:
                break
        print("\n(stream finished)")


if __name__ == "__main__":
    asyncio.run(main())
