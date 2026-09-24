"""
Asynchronous high‑level client wrapper for the LLM‑Router API.

The :class:`AsyncLLMRouterClient` is the ``asyncio`` counterpart of
:class:`llm_router_lib.client.LLMRouterClient` (built on ``httpx``) and
exposes the exact same calling contract for every endpoint method:

* ``payload`` – a ready‑made Pydantic request model that is serialised via
  ``model_dump()``; **or**
* named keyword arguments (domain fields such as ``texts`` /
  ``user_last_statement``, plus ``model`` and optional generation options
  ``temperature`` / ``max_new_tokens``), from which the client builds the
  request model on the fly (shared logic in
  :func:`llm_router_lib.utils.payload.build_payload`).

On top of the 1:1 asynchronous equivalents of every synchronous method, the
client adds two streaming methods
(:meth:`AsyncLLMRouterClient.stream_conversation_with_model` and
:meth:`AsyncLLMRouterClient.stream_extended_conversation_with_model`) that
yield normalised :class:`~llm_router_lib.data_models.response.StreamEvent`
objects, plus a :meth:`AsyncLLMRouterClient.collect_stream_text` helper that
aggregates a stream into the final text.
"""

import logging
from typing import Any, AsyncIterator, Dict, List, Optional, Type, Union

import httpx

from llm_router_lib.core.constants import (
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_RETRIES,
)
from llm_router_lib.utils.http_async import AsyncHttpRequester
from llm_router_lib.utils.payload import build_payload
from llm_router_lib.utils.stream import iter_events
from llm_router_lib.exceptions import LLMRouterError, NoArgsAndNoPayloadError
from llm_router_lib.services.conversation import (
    ConversationWithModelService,
    ExtendedConversationWithModelService,
)
from llm_router_lib.services.health import PingService, VersionService, ModelsService
from llm_router_lib.services.utils import (
    Polarity3cService,
    TranslateService,
    SimplifyTextService,
    GenerativeAnswerService,
    GenerateArticleFromTextService,
    CreateFullArticleFromTextsService,
    GenerateArticleFromTextsService,
    GenerateQuestionsService,
    GenerateLabelService,
)
from llm_router_lib.data_models.builtin_chat import (
    ConversationWithModelRequest,
    ExtendedConversationWithModelRequest,
)
from llm_router_lib.data_models.builtin_utils import (
    Polarity3cModel,
    TranslateModel,
    SimplifyTextModel,
    GenerativeAnswerModel,
    GenerateArticleFromTextModel,
    CreateFullArticleFromTextsModel,
    GenerateArticleFromTextsModel,
    GenerateQuestionsModel,
    GenerateLabelModel,
)
from llm_router_lib.data_models.response import (
    PingResponse,
    VersionResponse,
    ModelsListResponse,
    ConversationResponse,
    ExtendedConversationResponse,
    Polarity3cResponse,
    TranslateResponse,
    SimplifyTextResponse,
    GenerativeAnswerResponse,
    GenerateArticleFromTextResponse,
    GenerateArticleFromTextsResponse,
    CreateFullArticleFromTextsResponse,
    GenerateQuestionsResponse,
    GenerateLabelResponse,
    StreamEvent,
)


class AsyncLLMRouterClient:
    """
    Async public client exposing the core LLM‑Router endpoints.

    A drop‑in ``async`` alternative to
    :class:`llm_router_lib.client.LLMRouterClient`: the same methods, the
    same keyword‑only calling contract and the same typed response models,
    backed by :class:`~llm_router_lib.utils.http_async.AsyncHttpRequester`
    (``httpx``) with the same retry and error‑translation policy.

    Intended for use from ``asyncio`` applications (e.g. FastAPI) where the
    synchronous client would block the event loop.

    Attributes
    ----------
    base_url : str
        Normalised base URL of the router API (trailing slash stripped).
    token : Optional[str]
        Bearer token used for authentication; may be ``None`` for
        unauthenticated endpoints.
    timeout : int
        Per‑request timeout in seconds.
    retries : int
        Number of retry attempts for transient HTTP errors.
    stream_timeout : Optional[float]
        Read timeout for streaming requests; ``None`` disables the read
        timeout (recommended – long generations must not be cut off).
    http : AsyncHttpRequester
        Helper instance that performs the actual HTTP calls.
    logger : logging.Logger
        Logger used for debugging and error reporting.
    """

    def __init__(
        self,
        api: str,
        token: Optional[str] = None,
        timeout: Optional[int] = None,
        retries: Optional[int] = None,
        logger: Optional[logging.Logger] = None,
        default_model: Optional[str] = None,
        stream_timeout: Optional[float] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        """
        Initialise the async client with connection settings.

        Parameters
        ----------
        api : str
            Base URL of the router (e.g. ``"https://router.example.com"``).
        token : Optional[str]
            Authentication token; if omitted the ``Authorization`` header is
            not sent.
        timeout : int, default ``DEFAULT_TIMEOUT_SECONDS``
            Seconds to wait for a response before timing out.
        retries : int, default ``DEFAULT_RETRIES``
            Number of automatic retry attempts for HTTP status codes defined
            in the transport's retry policy.
        logger : Optional[logging.Logger]
            Custom logger; if ``None`` a module‑level logger is created.
        default_model : Optional[str]
            Default model name. Will be used in case when
            model_name in any service is not given.
        stream_timeout : Optional[float], default ``None``
            Read/write timeout (seconds) applied to the body of streaming
            requests.  ``None`` disables the read timeout so that long
            generations are not interrupted; the connect timeout stays
            ``timeout``.
        transport : Optional[httpx.BaseTransport]
            Custom ``httpx`` transport (e.g. ``httpx.MockTransport`` in
            tests); if omitted, the default transport is used.
        """
        self.base_url = api.rstrip("/")
        self.token = token

        self.default_model = default_model

        # Resolve lazy defaults from the centralised constants module.
        effective_timeout = (
            timeout if timeout is not None else DEFAULT_TIMEOUT_SECONDS
        )
        effective_retries = retries if retries is not None else DEFAULT_RETRIES
        self.timeout = effective_timeout
        self.retries = effective_retries
        self.stream_timeout = stream_timeout

        self.http = AsyncHttpRequester(
            base_url=self.base_url,
            token=self.token or "",
            timeout=effective_timeout,
            retries=effective_retries,
            transport=transport,
        )

        self.logger = logger or logging.getLogger(__name__)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def aclose(self) -> None:
        """Close the underlying HTTP client to release connections."""
        await self.http.aclose()

    async def __aenter__(self) -> "AsyncLLMRouterClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ #
    # Shared plumbing
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_json(resp: httpx.Response, endpoint: str) -> Dict[str, Any]:
        """Parse the response as JSON, raising ``LLMRouterError`` on failure."""
        try:
            return resp.json()
        except ValueError as inner_exc:
            raise LLMRouterError(
                f"Invalid JSON response from {endpoint}: {inner_exc}"
            ) from inner_exc

    async def _get_json(self, service_cls: type) -> Dict[str, Any]:
        """Perform a GET against ``service_cls.endpoint`` and parse the JSON body."""
        resp = await self.http.get(service_cls.endpoint)
        return self._parse_json(resp, service_cls.endpoint)

    async def _post_json(
        self, service_cls: type, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Perform a POST against ``service_cls.endpoint`` and parse the JSON body."""
        resp = await self.http.post(service_cls.endpoint, json=payload)
        return self._parse_json(resp, service_cls.endpoint)

    # ------------------------------------------------------------------ #
    # Health / meta endpoints
    # ------------------------------------------------------------------ #
    async def ping(self) -> PingResponse:
        """
        Perform a health‑check request against the router (``GET /api/ping``).

        Returns
        -------
        PingResponse
            Validated :class:`PingResponse` (``status`` and ``body`` fields).
        """
        return PingResponse.model_validate(
            await self._get_json(PingService)
        )

    async def version(self) -> VersionResponse:
        """
        Retrieve version information (``GET /api/version``).

        Returns
        -------
        VersionResponse
            Validated :class:`VersionResponse` exposing the router version.
        """
        return VersionResponse.model_validate(
            await self._get_json(VersionService)
        )

    async def models(self) -> ModelsListResponse:
        """
        List the models currently available on the router (``GET /v1/models``).

        Returns
        -------
        ModelsListResponse
            Validated :class:`ModelsListResponse`; read the ``data`` field for
            the full entries or the ``ids`` property for just the names.
        """
        return ModelsListResponse.model_validate(
            await self._get_json(ModelsService)
        )

    # ------------------------------------------------------------------ #
    # Conversation endpoints
    # ------------------------------------------------------------------ #
    async def conversation_with_model(
        self,
        *,
        payload: Optional[ConversationWithModelRequest] = None,
        user_last_statement: Optional[str] = None,
        historical_messages: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> ConversationResponse:
        """
        Call the standard conversation endpoint (async, non‑streaming).

        Same unified contract as
        :meth:`LLMRouterClient.conversation_with_model`: pass a prebuilt
        ``payload`` model or the named keyword arguments.

        Returns
        -------
        ConversationResponse
            Validated :class:`ConversationResponse`; ``response`` holds the
            reply text.

        See Also
        --------
        stream_conversation_with_model : streaming variant of this method.
        """
        request = build_payload(
            model_cls=ConversationWithModelService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            user_last_statement=user_last_statement,
            historical_messages=historical_messages,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return ConversationResponse.model_validate(
            await self._post_json(ConversationWithModelService, request)
        )

    async def extended_conversation_with_model(
        self,
        *,
        payload: Optional[ExtendedConversationWithModelRequest] = None,
        user_last_statement: Optional[str] = None,
        historical_messages: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> ExtendedConversationResponse:
        """
        Call the extended conversation endpoint (async, non‑streaming).

        Same unified contract as
        :meth:`LLMRouterClient.extended_conversation_with_model`.

        Returns
        -------
        ExtendedConversationResponse
            Validated :class:`ExtendedConversationResponse`; ``response``
            holds the reply text.

        See Also
        --------
        stream_extended_conversation_with_model : streaming variant.
        """
        request = build_payload(
            model_cls=ExtendedConversationWithModelService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            user_last_statement=user_last_statement,
            historical_messages=historical_messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return ExtendedConversationResponse.model_validate(
            await self._post_json(
                ExtendedConversationWithModelService, request
            )
        )

    # ------------------------------------------------------------------ #
    # Streaming conversation endpoints
    # ------------------------------------------------------------------ #
    async def stream_conversation_with_model(
        self,
        *,
        payload: Optional[ConversationWithModelRequest] = None,
        user_last_statement: Optional[str] = None,
        historical_messages: Optional[List[Dict[str, str]]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        Call the conversation endpoint with streaming (SSE) and yield events.

        The request is sent with ``stream: true`` (injected into the payload,
        since the request models do not carry a ``stream`` field) and the
        response body is consumed line by line.  Every content‑bearing chunk
        – OpenAI‑compatible or Ollama NDJSON, whichever the downstream
        provider emits – is normalised into a
        :class:`~llm_router_lib.data_models.response.StreamEvent`.

        Yields
        ------
        StreamEvent
            ``text`` is the extracted text delta, ``raw`` the original parsed
            chunk and ``done`` marks the end of the generation.

        Raises
        ------
        LLMRouterError
            On HTTP errors or when the stream contains an error chunk.

        Example
        -------
        >>> async with AsyncLLMRouterClient(api=api, token=token) as client:
        ...     async for event in client.stream_conversation_with_model(
        ...         user_last_statement="Hi!", model="gemma"
        ...     ):
        ...         print(event.text, end="", flush=True)
        """
        request = build_payload(
            model_cls=ConversationWithModelService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            user_last_statement=user_last_statement,
            historical_messages=historical_messages,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        request["stream"] = True
        async with self.http.stream(
            "POST",
            ConversationWithModelService.endpoint,
            json=request,
            timeout=self.stream_timeout,
        ) as resp:
            async for event in iter_events(resp, self.logger):
                yield event

    async def stream_extended_conversation_with_model(
        self,
        *,
        payload: Optional[ExtendedConversationWithModelRequest] = None,
        user_last_statement: Optional[str] = None,
        historical_messages: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        Call the extended conversation endpoint with streaming (SSE).

        Streaming variant of
        :meth:`extended_conversation_with_model`; see
        :meth:`stream_conversation_with_model` for the event contract.
        """
        request = build_payload(
            model_cls=ExtendedConversationWithModelService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            user_last_statement=user_last_statement,
            historical_messages=historical_messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        request["stream"] = True
        async with self.http.stream(
            "POST",
            ExtendedConversationWithModelService.endpoint,
            json=request,
            timeout=self.stream_timeout,
        ) as resp:
            async for event in iter_events(resp, self.logger):
                yield event

    @staticmethod
    async def collect_stream_text(events: AsyncIterator[StreamEvent]) -> str:
        """
        Aggregate a stream of events into the final reply text.

        Parameters
        ----------
        events : AsyncIterator[StreamEvent]
            An async generator produced by one of the ``stream_*`` methods.

        Returns
        -------
        str
            The concatenation of all non‑empty event texts.
        """
        parts: List[str] = []
        async for event in events:
            if event.text:
                parts.append(event.text)
        return "".join(parts)

    # ------------------------------------------------------------------ #
    # Utility endpoints
    # ------------------------------------------------------------------ #
    async def polarity_3c(
        self,
        *,
        payload: Optional[Polarity3cModel] = None,
        texts: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> Polarity3cResponse:
        """
        Detect 3‑class polarity for a list of texts (``POST /api/polarity_3c``).

        Returns
        -------
        Polarity3cResponse
            Validated :class:`Polarity3cResponse`; ``response`` is a list of
            ``{original, polarity}`` items, one per input text.
        """
        request = build_payload(
            model_cls=Polarity3cService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return Polarity3cResponse.model_validate(
            await self._post_json(Polarity3cService, request)
        )

    async def translate(
        self,
        *,
        payload: Optional[TranslateModel] = None,
        texts: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> TranslateResponse:
        """
        Translate a list of texts (``POST /api/translate``).

        Returns
        -------
        TranslateResponse
            Validated :class:`TranslateResponse`; ``response`` is a list of
            ``{original, translated}`` items.
        """
        request = build_payload(
            model_cls=TranslateService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return TranslateResponse.model_validate(
            await self._post_json(TranslateService, request)
        )

    async def simplify_text(
        self,
        *,
        payload: Optional[SimplifyTextModel] = None,
        texts: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> SimplifyTextResponse:
        """
        Simplify a list of texts (``POST /api/simplify_text``).

        Returns
        -------
        SimplifyTextResponse
            Validated :class:`SimplifyTextResponse`; ``response`` is a list
            of simplified text strings.
        """
        request = build_payload(
            model_cls=SimplifyTextService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return SimplifyTextResponse.model_validate(
            await self._post_json(SimplifyTextService, request)
        )

    async def generative_answer(
        self,
        *,
        payload: Optional[GenerativeAnswerModel] = None,
        texts: Optional[Union[Dict[str, List[str]], List[str]]] = None,
        question_str: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> GenerativeAnswerResponse:
        """
        Generate an answer to a question based on a list of texts
        (``POST /api/generative_answer``).

        Returns
        -------
        GenerativeAnswerResponse
            Validated :class:`GenerativeAnswerResponse`; ``response`` holds
            the generated answer text.
        """
        request = build_payload(
            model_cls=GenerativeAnswerService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            question_str=question_str,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return GenerativeAnswerResponse.model_validate(
            await self._post_json(GenerativeAnswerService, request)
        )

    async def generate_article_from_text(
        self,
        *,
        payload: Optional[GenerateArticleFromTextModel] = None,
        text: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> GenerateArticleFromTextResponse:
        """
        Generate a short article from a single text
        (``POST /api/generate_article_from_text``).

        Returns
        -------
        GenerateArticleFromTextResponse
            Validated :class:`GenerateArticleFromTextResponse`.
        """
        request = build_payload(
            model_cls=GenerateArticleFromTextService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            text=text,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return GenerateArticleFromTextResponse.model_validate(
            await self._post_json(GenerateArticleFromTextService, request)
        )

    async def generate_article_from_texts(
        self,
        *,
        payload: Optional[GenerateArticleFromTextsModel] = None,
        texts: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> GenerateArticleFromTextsResponse:
        """
        Generate a short article summarising a list of texts
        (``POST /api/generate_article_from_texts``).

        Returns
        -------
        GenerateArticleFromTextsResponse
            Validated :class:`GenerateArticleFromTextsResponse`.
        """
        request = build_payload(
            model_cls=GenerateArticleFromTextsService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return GenerateArticleFromTextsResponse.model_validate(
            await self._post_json(GenerateArticleFromTextsService, request)
        )

    async def create_full_article_from_texts(
        self,
        *,
        payload: Optional[CreateFullArticleFromTextsModel] = None,
        user_query: Optional[str] = None,
        texts: Optional[List[str]] = None,
        article_type: Optional[str] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> CreateFullArticleFromTextsResponse:
        """
        Create a fuller article framed by ``user_query`` from a list of texts
        (``POST /api/create_full_article_from_texts``).

        Returns
        -------
        CreateFullArticleFromTextsResponse
            Validated :class:`CreateFullArticleFromTextsResponse`.
        """
        request = build_payload(
            model_cls=CreateFullArticleFromTextsService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            user_query=user_query,
            texts=texts,
            article_type=article_type,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return CreateFullArticleFromTextsResponse.model_validate(
            await self._post_json(
                CreateFullArticleFromTextsService, request
            )
        )

    async def generate_questions(
        self,
        *,
        payload: Optional[GenerateQuestionsModel] = None,
        texts: Optional[List[str]] = None,
        number_of_questions: Optional[int] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> GenerateQuestionsResponse:
        """
        Generate questions from multiple input texts
        (``POST /api/generate_questions``).

        Returns
        -------
        GenerateQuestionsResponse
            Validated :class:`GenerateQuestionsResponse`; ``response`` is a
            list of ``{text, questions}`` items.
        """
        request = build_payload(
            model_cls=GenerateQuestionsService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            number_of_questions=number_of_questions,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return GenerateQuestionsResponse.model_validate(
            await self._post_json(GenerateQuestionsService, request)
        )

    async def generate_label(
        self,
        *,
        payload: Optional[GenerateLabelModel] = None,
        texts: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_new_tokens: Optional[int] = None,
    ) -> GenerateLabelResponse:
        """
        Generate a category label for a list of texts
        (``POST /api/generate_label``).

        Returns
        -------
        GenerateLabelResponse
            Validated :class:`GenerateLabelResponse`; ``response`` is the
            generated category label.
        """
        request = build_payload(
            model_cls=GenerateLabelService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return GenerateLabelResponse.model_validate(
            await self._post_json(GenerateLabelService, request)
        )
