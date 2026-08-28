"""
High‑level client wrapper for the LLM‑Router API.

The :class:`LLMRouterClient` aggregates the low‑level ``HttpRequester`` with
the service‑layer classes (conversation, utility endpoints) to provide a
convenient, type‑safe Python interface.

Every endpoint method exposes **one unified calling contract**:

* ``payload`` – a ready‑made Pydantic request model (e.g.
  :class:`Polarity3cModel`) that is serialised via ``model_dump()``; **or**
* named keyword arguments (domain fields such as ``texts`` /
  ``user_last_statement``, plus ``model`` and optional generation options
  ``temperature`` / ``max_new_tokens``), from which the client builds the
  request model on the fly.  All generation defaults come from the Pydantic
  models themselves (``GenerativeOptions``).

Raw ``dict`` payloads are **not** accepted – construct the Pydantic model
explicitly (``MyModel(**kwargs)``) and pass the instance as ``payload``.
Each public method validates the raw JSON response against the matching
Pydantic model (see :mod:`llm_router_lib.data_models.response`) and returns
that typed model rather than a free‑form ``dict``.
"""

import logging

from pydantic import BaseModel, ValidationError

from llm_router_lib.core.constants import (
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_RETRIES,
)
from llm_router_lib.services.health import PingService, VersionService, ModelsService
from llm_router_lib.utils.http import HttpRequester
from llm_router_lib.exceptions import NoArgsAndNoPayloadError
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
from llm_router_lib.services.conversation import (
    ConversationWithModelService,
    ExtendedConversationWithModelService,
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
)


class LLMRouterClient:
    """
    Public client exposing the core LLM‑Router endpoints.

    The client hides the details of HTTP construction, retry handling and
    payload validation.  It is intended for use by downstream applications that
    need to interact with the router in a Pythonic way.

    Every endpoint method follows the same unified contract: either pass a
    ready‑made Pydantic request model via ``payload``, or pass the named
    domain arguments (plus ``model`` and optional ``temperature`` /
    ``max_new_tokens``) and the client builds the request model for you.
    Raw ``dict`` payloads are no longer supported.

    Attributes
    ----------
    base_url : str
        Normalised base URL of the router API (trailing slash stripped).
    token : Optional[str]
        Bearer token used for authentication; may be ``None`` for unauthenticated
        endpoints.
    timeout : int
        Per‑request timeout in seconds.
    retries : int
        Number of retry attempts for transient HTTP errors.
    http : HttpRequester
        Helper instance that performs the actual HTTP calls.
    logger : logging.Logger
        Logger used for debugging and error reporting.
    """

    def __init__(
        self,
        api: str,
        token: str | None = None,
        timeout: int | None = None,
        retries: int | None = None,
        logger: logging.Logger | None = None,
        default_model: str | None = None,
    ) -> None:
        """
        Initialise the client with connection settings.

        Parameters
        ----------
        api : str
            Base URL of the router (e.g. ``"https://router.example.com"``).
        token : Optional[str]
            Authentication token; if omitted the ``Authorization`` header is not
            sent.
        timeout : int, default ``DEFAULT_TIMEOUT_SECONDS``
            Seconds to wait for a response before timing out.
        retries : int, default ``DEFAULT_RETRIES``
            Number of automatic retry attempts for HTTP status codes defined in
            ``HttpRequester``'s retry policy.
        logger : logging.Logger | None
            Custom logger; if ``None`` a module‑level logger is created.
        default_model: str | None
            Default model name. Will be used in case when
            model_name in any service is not given
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
        self.http = HttpRequester(
            base_url=self.base_url,
            token=self.token or "",
            timeout=effective_timeout,
            retries=effective_retries,
        )

        self.logger = logger or logging.getLogger(__name__)

    def close(self) -> None:
        """Close the underlying HTTP session to release resources."""
        self.http.close()

    def __enter__(self) -> "LLMRouterClient":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    def ping(self) -> PingResponse:
        """
        Perform a health‑check request against the router.

        This method invokes the ``/api/ping`` endpoint via :class:`PingService`
        and returns the parsed JSON response.  It is useful for quickly
        confirming that the service is up and reachable before making more
        expensive calls.

        Returns
        -------
        PingResponse
            Validated :class:`PingResponse` (``status`` and ``body`` fields),
            typically ``{"status": true, "body": "pong"}``.

        Raises
        ------
        LLMRouterError
            Propagated from the underlying service if the HTTP request fails
            or the response cannot be decoded as JSON.
        """
        return PingResponse.model_validate(
            PingService(self.http, self.logger).call_get()
        )

    def version(self) -> VersionResponse:
        """
        Retrieve version information for the running router instance.

        Calls the ``/api/version`` endpoint via :class:`VersionService`.  The
        returned dictionary may include keys such as ``version``, ``commit_hash``,
        ``build_date`` or other metadata the backend provides.

        Returns
        -------
        VersionResponse
            Validated :class:`VersionResponse` exposing the router ``version``.

        Raises
        ------
        LLMRouterError
            Propagated if the request fails or the response is not valid JSON.
        """
        return VersionResponse.model_validate(
            VersionService(self.http, self.logger).call_get()
        )

    def models(self) -> ModelsListResponse:
        """
        List the models currently available on the router.

        Calls the ``/v1/models`` endpoint via :class:`ModelsService` and
        extracts the identifier (``id`` field) of each entry.  This is useful
        for discovering which model names can be passed to the other client
        methods (e.g. ``conversation_with_model``).

        Returns
        -------
        ModelsListResponse
            Validated :class:`ModelsListResponse`; read the ``data`` field for the
            full entries or the ``ids`` property for just the model names, e.g.
            ``["google/gemma-3-12b-it", "speakleash/Bielik-11B-v2.3-Instruct"]``.

        Raises
        ------
        LLMRouterError
            Propagated from the underlying service if the HTTP request fails
            or the response cannot be decoded as JSON.
        """
        response = ModelsService(self.http, self.logger).call_get()
        return ModelsListResponse.model_validate(response)

    # ------------------------------------------------------------------ #
    def conversation_with_model(
        self,
        *,
        payload: ConversationWithModelRequest | None = None,
        user_last_statement: str | None = None,
        historical_messages: list[dict[str, str]] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_new_tokens: int | None = None,
    ) -> ConversationResponse:
        """
        Call the standard conversation endpoint.

        The method can be called in two equivalent ways:

        1. **Prebuilt payload** – pass ``payload`` as a
           :class:`ConversationWithModelRequest` instance; it is serialised
           with ``model_dump()`` and sent as‑is.
        2. **Named arguments** – pass ``user_last_statement`` (plus optional
           ``historical_messages``, ``model``, ``temperature`` and
           ``max_new_tokens``); the client builds a
           :class:`ConversationWithModelRequest` from them, using the client's
           ``default_model`` when ``model`` is omitted.

        Passing a raw ``dict`` as ``payload`` raises :class:`TypeError`.
        If neither a payload nor enough named arguments are provided, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : ConversationWithModelRequest | None
            Optional pre‑constructed request model.
        user_last_statement : str | None
            The latest user utterance that the model should respond to
            (required unless ``payload`` is supplied).
        historical_messages : list[dict[str, str]] | None
            Optional previous dialogue turns; each dict must contain ``role``
            (``"user"`` / ``"assistant"``) and ``content`` keys.
        model : str | None
            Model identifier; falls back to the client ``default_model``.
        temperature : float | None
            Sampling temperature (only used when building the payload from
            arguments).
        max_new_tokens : int | None
            Maximum number of tokens to generate (only used when building the
            payload from arguments).

        Returns
        -------
        ConversationResponse
            Validated :class:`ConversationResponse`; ``response`` holds the
            reply text.

        Raises
        ------
        TypeError
            If ``payload`` is a raw ``dict``.
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and the named arguments do not contain
            all required fields (``user_last_statement`` or a resolvable model
            name).
        LLMRouterError
            Propagated from the underlying service on HTTP/JSON failures.
        """
        request = self._build_payload(
            model_cls=ConversationWithModelService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            user_last_statement=user_last_statement,
            historical_messages=historical_messages,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return ConversationResponse.model_validate(
            ConversationWithModelService(self.http, self.logger).call_post(request)
        )

    def extended_conversation_with_model(
        self,
        *,
        payload: ExtendedConversationWithModelRequest | None = None,
        user_last_statement: str | None = None,
        historical_messages: list[dict[str, str]] | None = None,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_new_tokens: int | None = None,
    ) -> ExtendedConversationResponse:
        """
        Call the extended conversation endpoint that supports an explicit
        system prompt.

        The method can be called in two equivalent ways:

        1. **Prebuilt payload** – pass ``payload`` as an
           :class:`ExtendedConversationWithModelRequest` instance; it is
           serialised with ``model_dump()`` and sent as‑is.
        2. **Named arguments** – pass ``user_last_statement`` and
           ``system_prompt`` (plus optional ``historical_messages``, ``model``,
           ``temperature`` and ``max_new_tokens``); the client builds an
           :class:`ExtendedConversationWithModelRequest` from them, using the
           client's ``default_model`` when ``model`` is omitted.

        Passing a raw ``dict`` as ``payload`` raises :class:`TypeError`.
        If neither a payload nor enough named arguments are provided, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : ExtendedConversationWithModelRequest | None
            Optional pre‑constructed request model.
        user_last_statement : str | None
            The latest user utterance that the model should respond to
            (required unless ``payload`` is supplied).
        historical_messages : list[dict[str, str]] | None
            Optional previous dialogue turns; each dict must contain ``role``
            (``"user"`` / ``"assistant"``) and ``content`` keys.
        system_prompt : str | None
            Explicit system prompt prepended to the conversation (required
            unless ``payload`` is supplied).
        model : str | None
            Model identifier; falls back to the client ``default_model``.
        temperature : float | None
            Sampling temperature (only used when building the payload from
            arguments).
        max_new_tokens : int | None
            Maximum number of tokens to generate (only used when building the
            payload from arguments).

        Returns
        -------
        ExtendedConversationResponse
            Validated :class:`ExtendedConversationResponse`; ``response`` holds
            the reply text.

        Raises
        ------
        TypeError
            If ``payload`` is a raw ``dict``.
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and the named arguments do not contain
            all required fields (``user_last_statement``, ``system_prompt`` or
            a resolvable model name).
        LLMRouterError
            Propagated from the underlying service on HTTP/JSON failures.
        """
        request = self._build_payload(
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
            ExtendedConversationWithModelService(self.http, self.logger).call_post(
                request
            )
        )

    # ------------------------------------------------------------------ #
    def polarity_3c(
        self,
        *,
        payload: Polarity3cModel | None = None,
        texts: list[str] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_new_tokens: int | None = None,
    ) -> Polarity3cResponse:
        """
        Detect 3‑class polarity (ambivalent, positive, negative) for a list of
        texts using the ``/api/polarity_3c`` endpoint.

        The method can be called in two equivalent ways:

        1. **Prebuilt payload** – pass ``payload`` as a
           :class:`Polarity3cModel` instance; it is serialised with
           ``model_dump()`` and sent as‑is.
        2. **Named arguments** – pass ``texts`` (plus optional ``model``,
           ``temperature`` and ``max_new_tokens``); the client builds a
           :class:`Polarity3cModel` from them, using the client's
           ``default_model`` when ``model`` is omitted.

        Passing a raw ``dict`` as ``payload`` raises :class:`TypeError`.
        If neither a payload nor enough named arguments are provided, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : Polarity3cModel | None
            Optional pre‑constructed request model.
        texts : list[str] | None
            List of source strings to classify (required unless ``payload`` is
            supplied).
        model : str | None
            Model identifier to be used for classification; falls back to the
            client ``default_model``.
        temperature : float | None
            Sampling temperature (only used when building the payload from
            arguments).
        max_new_tokens : int | None
            Maximum number of tokens to generate (only used when building the
            payload from arguments).

        Returns
        -------
        Polarity3cResponse
            Validated :class:`Polarity3cResponse`; ``response`` is a list of
            ``{original, polarity}`` items, one per input text.

        Raises
        ------
        TypeError
            If ``payload`` is a raw ``dict``.
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and the named arguments do not contain
            all required fields (``texts`` or a resolvable model name).
        LLMRouterError
            Propagated from the underlying service on HTTP/JSON failures.
        """
        request = self._build_payload(
            model_cls=Polarity3cService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return Polarity3cResponse.model_validate(
            Polarity3cService(self.http, self.logger).call_post(request)
        )

    def translate(
        self,
        *,
        payload: TranslateModel | None = None,
        texts: list[str] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_new_tokens: int | None = None,
    ) -> TranslateResponse:
        """
        Translate a list of texts using the ``/api/translate`` endpoint.

        The method can be called in two equivalent ways:

        1. **Prebuilt payload** – pass ``payload`` as a
           :class:`TranslateModel` instance; it is serialised with
           ``model_dump()`` and sent as‑is.
        2. **Named arguments** – pass ``texts`` (plus optional ``model``,
           ``temperature`` and ``max_new_tokens``); the client builds a
           :class:`TranslateModel` from them, using the client's
           ``default_model`` when ``model`` is omitted.

        Passing a raw ``dict`` as ``payload`` raises :class:`TypeError`.
        If neither a payload nor enough named arguments are provided, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : TranslateModel | None
            Optional pre‑constructed request model.
        texts : list[str] | None
            List of source strings to translate (required unless ``payload`` is
            supplied).
        model : str | None
            Model identifier to be used for translation; falls back to the
            client ``default_model``.
        temperature : float | None
            Sampling temperature (only used when building the payload from
            arguments).
        max_new_tokens : int | None
            Maximum number of tokens to generate (only used when building the
            payload from arguments).

        Returns
        -------
        TranslateResponse
            Validated :class:`TranslateResponse`; ``response`` is a list of
            ``{original, translated}`` items, one per input text.

        Raises
        ------
        TypeError
            If ``payload`` is a raw ``dict``.
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and the named arguments do not contain
            all required fields (``texts`` or a resolvable model name).
        LLMRouterError
            Propagated from the underlying service on HTTP/JSON failures.
        """
        request = self._build_payload(
            model_cls=TranslateService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return TranslateResponse.model_validate(
            TranslateService(self.http, self.logger).call_post(request)
        )

    def simplify_text(
        self,
        *,
        payload: SimplifyTextModel | None = None,
        texts: list[str] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_new_tokens: int | None = None,
    ) -> SimplifyTextResponse:
        """
        Simplify a list of texts using the ``/api/simplify_text`` endpoint.

        The method can be called in two equivalent ways:

        1. **Prebuilt payload** – pass ``payload`` as a
           :class:`SimplifyTextModel` instance; it is serialised with
           ``model_dump()`` and sent as‑is.
        2. **Named arguments** – pass ``texts`` (plus optional ``model``,
           ``temperature`` and ``max_new_tokens``); the client builds a
           :class:`SimplifyTextModel` from them, using the client's
           ``default_model`` when ``model`` is omitted.

        Passing a raw ``dict`` as ``payload`` raises :class:`TypeError`.
        If neither a payload nor enough named arguments are provided, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : SimplifyTextModel | None
            Optional pre‑constructed request model.
        texts : list[str] | None
            List of source strings to simplify (required unless ``payload`` is
            supplied).
        model : str | None
            Model identifier to be used for simplification; falls back to the
            client ``default_model``.
        temperature : float | None
            Sampling temperature (only used when building the payload from
            arguments).
        max_new_tokens : int | None
            Maximum number of tokens to generate (only used when building the
            payload from arguments).

        Returns
        -------
        SimplifyTextResponse
            Validated :class:`SimplifyTextResponse`; ``response`` is a list of
            the simplified texts.

        Raises
        ------
        TypeError
            If ``payload`` is a raw ``dict``.
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and the named arguments do not contain
            all required fields (``texts`` or a resolvable model name).
        LLMRouterError
            Propagated from the underlying service on HTTP/JSON failures.
        """
        request = self._build_payload(
            model_cls=SimplifyTextService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return SimplifyTextResponse.model_validate(
            SimplifyTextService(self.http, self.logger).call_post(request)
        )

    def generative_answer(
        self,
        *,
        payload: GenerativeAnswerModel | None = None,
        texts: dict[str, list[str]] | list[str] | None = None,
        question_str: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_new_tokens: int | None = None,
    ) -> GenerativeAnswerResponse:
        """
        Answer a question based on a context (RAG) using the
        ``/api/generative_answer`` endpoint.

        The method can be called in two equivalent ways:

        1. **Prebuilt payload** – pass ``payload`` as a
           :class:`GenerativeAnswerModel` instance; it is serialised with
           ``model_dump()`` and sent as‑is.  This is the only way to set the
           advanced options (``doc_name_in_answer``, ``question_prompt``,
           ``system_prompt``).
        2. **Named arguments** – pass ``texts`` and ``question_str`` (plus
           optional ``model``, ``temperature`` and ``max_new_tokens``); the
           client builds a :class:`GenerativeAnswerModel` from them, using the
           client's ``default_model`` when ``model`` is omitted.

        ``texts`` is either a mapping of document name → list of passages or a
        flat list of passages.

        Passing a raw ``dict`` as ``payload`` raises :class:`TypeError`.
        If neither a payload nor enough named arguments are provided, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : GenerativeAnswerModel | None
            Optional pre‑constructed request model.
        texts : dict[str, list[str]] | list[str] | None
            Knowledge base passages (required unless ``payload`` is supplied).
        question_str : str | None
            The user's question to be answered (required unless ``payload`` is
            supplied).
        model : str | None
            Model identifier; falls back to the client ``default_model``.
        temperature : float | None
            Sampling temperature (only used when building the payload from
            arguments).
        max_new_tokens : int | None
            Maximum number of tokens to generate (only used when building the
            payload from arguments).

        Returns
        -------
        GenerativeAnswerResponse
            Validated :class:`GenerativeAnswerResponse`; ``response`` is the
            generated answer text.

        Raises
        ------
        TypeError
            If ``payload`` is a raw ``dict``.
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and the named arguments do not contain
            all required fields (``texts``, ``question_str`` or a resolvable
            model name).
        LLMRouterError
            Propagated from the underlying service on HTTP/JSON failures.
        """
        request = self._build_payload(
            model_cls=GenerativeAnswerService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            question_str=question_str,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return GenerativeAnswerResponse.model_validate(
            GenerativeAnswerService(self.http, self.logger).call_post(request)
        )

    def generate_article_from_text(
        self,
        *,
        payload: GenerateArticleFromTextModel | None = None,
        text: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_new_tokens: int | None = None,
    ) -> GenerateArticleFromTextResponse:
        """
        Expand a single source text into a full article using the
        ``/api/generate_article_from_text`` endpoint.

        The method can be called in two equivalent ways:

        1. **Prebuilt payload** – pass ``payload`` as a
           :class:`GenerateArticleFromTextModel` instance; it is serialised
           with ``model_dump()`` and sent as‑is.
        2. **Named arguments** – pass ``text`` (plus optional ``model``,
           ``temperature`` and ``max_new_tokens``); the client builds a
           :class:`GenerateArticleFromTextModel` from them, using the client's
           ``default_model`` when ``model`` is omitted.

        Passing a raw ``dict`` as ``payload`` raises :class:`TypeError`.
        If neither a payload nor enough named arguments are provided, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : GenerateArticleFromTextModel | None
            Optional pre‑constructed request model.
        text : str | None
            The source text (e.g. a news snippet) to be expanded into an
            article (required unless ``payload`` is supplied).
        model : str | None
            Model identifier; falls back to the client ``default_model``.
        temperature : float | None
            Sampling temperature (only used when building the payload from
            arguments).
        max_new_tokens : int | None
            Maximum number of tokens to generate (only used when building the
            payload from arguments).

        Returns
        -------
        GenerateArticleFromTextResponse
            Validated :class:`GenerateArticleFromTextResponse`;
            ``response.article_text`` holds the generated article.

        Raises
        ------
        TypeError
            If ``payload`` is a raw ``dict``.
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and the named arguments do not contain
            all required fields (``text`` or a resolvable model name).
        LLMRouterError
            Propagated from the underlying service on HTTP/JSON failures.
        """
        request = self._build_payload(
            model_cls=GenerateArticleFromTextService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            text=text,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return GenerateArticleFromTextResponse.model_validate(
            GenerateArticleFromTextService(self.http, self.logger).call_post(request)
        )

    def generate_article_from_texts(
        self,
        *,
        payload: GenerateArticleFromTextsModel | None = None,
        texts: list[str] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_new_tokens: int | None = None,
    ) -> GenerateArticleFromTextsResponse:
        """
        Generate a short (~A4) article from multiple input texts using the
        ``/api/generate_article_from_texts`` endpoint.

        The method can be called in two equivalent ways:

        1. **Prebuilt payload** – pass ``payload`` as a
           :class:`GenerateArticleFromTextsModel` instance; it is serialised
           with ``model_dump()`` and sent as‑is.
        2. **Named arguments** – pass ``texts`` (plus optional ``model``,
           ``temperature`` and ``max_new_tokens``); the client builds a
           :class:`GenerateArticleFromTextsModel` from them, using the
           client's ``default_model`` when ``model`` is omitted.

        Passing a raw ``dict`` as ``payload`` raises :class:`TypeError`.
        If neither a payload nor enough named arguments are provided, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : GenerateArticleFromTextsModel | None
            Optional pre‑constructed request model.
        texts : list[str] | None
            Source texts from which to produce the article (required unless
            ``payload`` is supplied).
        model : str | None
            Model identifier; falls back to the client ``default_model``.
        temperature : float | None
            Sampling temperature (only used when building the payload from
            arguments).
        max_new_tokens : int | None
            Maximum number of tokens to generate (only used when building the
            payload from arguments).

        Returns
        -------
        GenerateArticleFromTextsResponse
            Validated :class:`GenerateArticleFromTextsResponse`;
            ``response.article_text`` holds the generated article.

        Raises
        ------
        TypeError
            If ``payload`` is a raw ``dict``.
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and the named arguments do not contain
            all required fields (``texts`` or a resolvable model name).
        LLMRouterError
            Propagated from the underlying service on HTTP/JSON failures.
        """
        request = self._build_payload(
            model_cls=GenerateArticleFromTextsService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return GenerateArticleFromTextsResponse.model_validate(
            GenerateArticleFromTextsService(self.http, self.logger).call_post(
                request
            )
        )

    def create_full_article_from_texts(
        self,
        *,
        payload: CreateFullArticleFromTextsModel | None = None,
        user_query: str | None = None,
        texts: list[str] | None = None,
        article_type: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_new_tokens: int | None = None,
    ) -> CreateFullArticleFromTextsResponse:
        """
        Create a full article from multiple input texts using the
        ``/api/create_full_article_from_texts`` endpoint.

        The method can be called in two equivalent ways:

        1. **Prebuilt payload** – pass ``payload`` as a
           :class:`CreateFullArticleFromTextsModel` instance; it is serialised
           with ``model_dump()`` and sent as‑is.
        2. **Named arguments** – pass ``user_query`` (plus optional ``texts``,
           ``article_type``, ``model``, ``temperature`` and ``max_new_tokens``);
           the client builds a :class:`CreateFullArticleFromTextsModel` from
           them, using the client's ``default_model`` when ``model`` is
           omitted.

        Passing a raw ``dict`` as ``payload`` raises :class:`TypeError`.
        If neither a payload nor enough named arguments are provided, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : CreateFullArticleFromTextsModel | None
            Optional pre‑constructed request model.
        user_query : str | None
            The query that frames the desired article (required unless
            ``payload`` is supplied).
        texts : list[str] | None
            Source texts that will be merged into the final article.
        article_type : str | None
            Optional identifier appended to the system prompt to influence the
            article's style or format.
        model : str | None
            Model identifier; falls back to the client ``default_model``.
        temperature : float | None
            Sampling temperature (only used when building the payload from
            arguments).
        max_new_tokens : int | None
            Maximum number of tokens to generate (only used when building the
            payload from arguments).

        Returns
        -------
        CreateFullArticleFromTextsResponse
            Validated :class:`CreateFullArticleFromTextsResponse`;
            ``response.article_text`` holds the generated article.

        Raises
        ------
        TypeError
            If ``payload`` is a raw ``dict``.
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and the named arguments do not contain
            all required fields (``user_query`` or a resolvable model name).
        LLMRouterError
            Propagated from the underlying service on HTTP/JSON failures.
        """
        request = self._build_payload(
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
            CreateFullArticleFromTextsService(self.http, self.logger).call_post(
                request
            )
        )

    def generate_questions(
        self,
        *,
        payload: GenerateQuestionsModel | None = None,
        texts: list[str] | None = None,
        number_of_questions: int | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_new_tokens: int | None = None,
    ) -> GenerateQuestionsResponse:
        """
        Generate questions from multiple input texts using the
        ``/api/generate_questions`` endpoint.

        The method can be called in two equivalent ways:

        1. **Prebuilt payload** – pass ``payload`` as a
           :class:`GenerateQuestionsModel` instance; it is serialised with
           ``model_dump()`` and sent as‑is.
        2. **Named arguments** – pass ``texts`` (plus optional
           ``number_of_questions``, ``model``, ``temperature`` and
           ``max_new_tokens``); the client builds a
           :class:`GenerateQuestionsModel` from them, using the client's
           ``default_model`` when ``model`` is omitted.

        Passing a raw ``dict`` as ``payload`` raises :class:`TypeError`.
        If neither a payload nor enough named arguments are provided, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : GenerateQuestionsModel | None
            Optional pre‑constructed request model.
        texts : list[str] | None
            List of source strings from which to generate questions (required
            unless ``payload`` is supplied).
        number_of_questions : int | None
            Desired number of questions per input text; defaults to the model
            default (``1``) when omitted.
        model : str | None
            Model identifier; falls back to the client ``default_model``.
        temperature : float | None
            Sampling temperature (only used when building the payload from
            arguments).
        max_new_tokens : int | None
            Maximum number of tokens to generate (only used when building the
            payload from arguments).

        Returns
        -------
        GenerateQuestionsResponse
            Validated :class:`GenerateQuestionsResponse`; ``response`` is a
            list of ``{text, questions}`` items, one per input text.

        Raises
        ------
        TypeError
            If ``payload`` is a raw ``dict``.
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and the named arguments do not contain
            all required fields (``texts`` or a resolvable model name).
        LLMRouterError
            Propagated from the underlying service on HTTP/JSON failures.
        """
        request = self._build_payload(
            model_cls=GenerateQuestionsService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            number_of_questions=number_of_questions,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return GenerateQuestionsResponse.model_validate(
            GenerateQuestionsService(self.http, self.logger).call_post(request)
        )

    def generate_label(
        self,
        *,
        payload: GenerateLabelModel | None = None,
        texts: list[str] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_new_tokens: int | None = None,
    ) -> GenerateLabelResponse:
        """
        Generate a category name (label) for a list of texts using the
        ``/api/generate_label`` endpoint.

        The endpoint receives a list of related texts and returns a single,
        concise category name that best captures their common essence.

        The method can be called in two equivalent ways:

        1. **Prebuilt payload** – pass ``payload`` as a
           :class:`GenerateLabelModel` instance; it is serialised with
           ``model_dump()`` and sent as‑is.
        2. **Named arguments** – pass ``texts`` (plus optional ``model``,
           ``temperature`` and ``max_new_tokens``); the client builds a
           :class:`GenerateLabelModel` from them, using the client's
           ``default_model`` when ``model`` is omitted.

        Passing a raw ``dict`` as ``payload`` raises :class:`TypeError`.
        If neither a payload nor enough named arguments are provided, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : GenerateLabelModel | None
            Optional pre‑constructed request model.
        texts : list[str] | None
            List of related source strings whose shared essence should be
            captured by a single category name (required unless ``payload`` is
            supplied).
        model : str | None
            Model identifier; falls back to the client ``default_model``.
        temperature : float | None
            Sampling temperature (only used when building the payload from
            arguments).
        max_new_tokens : int | None
            Maximum number of tokens for the generated label (only used when
            building the payload from arguments).

        Returns
        -------
        GenerateLabelResponse
            Validated :class:`GenerateLabelResponse`; ``response`` is the
            generated category label.

        Raises
        ------
        TypeError
            If ``payload`` is a raw ``dict``.
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and the named arguments do not contain
            all required fields (``texts`` or a resolvable model name).
        LLMRouterError
            Propagated from the underlying service on HTTP/JSON failures.
        """
        request = self._build_payload(
            model_cls=GenerateLabelService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return GenerateLabelResponse.model_validate(
            GenerateLabelService(self.http, self.logger).call_post(request)
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_payload(
        *,
        model_cls: type[BaseModel] | None,
        payload_arg: object,
        **extra: object,
    ) -> dict[str, object]:
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
