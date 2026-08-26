"""
High‑level client wrapper for the LLM‑Router API.

The :class:`LLMRouterClient` aggregates the low‑level ``HttpRequester`` with
the service‑layer classes (conversation, extended conversation, translation)
to provide a convenient, type‑safe Python interface.  Callers can pass either
a dictionary or a Pydantic model instance; the client takes care of converting
the model to a plain ``dict`` before invoking the appropriate service.
"""

import logging
from typing import Optional, Dict, Any, Union, List

from pydantic import BaseModel

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

# ------------------------------------------------------------------ #
# Type aliases for payload parameter union types (repeated across methods).
# ------------------------------------------------------------------ #
_ConvPayload = Union[Dict[str, Any], ConversationWithModelService.model_cls]
_ExtConvPayload = Union[
    Dict[str, Any], ExtendedConversationWithModelService.model_cls
]


class LLMRouterClient:
    """
    Public client exposing the core LLM‑Router endpoints.

    The client hides the details of HTTP construction, retry handling and
    payload validation.  It is intended for use by downstream applications that
    need to interact with the router in a Pythonic way.

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
        token: Optional[str] = None,
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
    def ping(self) -> Dict[str, Any]:
        """
        Perform a health‑check request against the router.

        This method invokes the ``/api/ping`` endpoint via :class:`PingService`
        and returns the parsed JSON response.  It is useful for quickly
        confirming that the service is up and reachable before making more
        expensive calls.

        Returns
        -------
        dict
            The JSON payload returned by the router, typically containing a
            ``status`` field (e.g. ``{"status": "ok"}``).

        Raises
        ------
        LLMRouterError
            Propagated from the underlying service if the HTTP request fails
            or the response cannot be decoded as JSON.
        """
        return PingService(self.http, self.logger).call_get()

    def version(self) -> Dict[str, Any]:
        """
        Retrieve version information for the running router instance.

        Calls the ``/api/version`` endpoint via :class:`VersionService`.  The
        returned dictionary may include keys such as ``version``, ``commit_hash``,
        ``build_date`` or other metadata the backend provides.

        Returns
        -------
        dict
            Parsed JSON containing version‑related data.

        Raises
        ------
        LLMRouterError
            Propagated if the request fails or the response is not valid JSON.
        """
        return VersionService(self.http, self.logger).call_get()

    def models(self) -> List[str]:
        """
        List the models currently available on the router.

        Calls the ``/v1/models`` endpoint via :class:`ModelsService` and
        extracts the identifier (``id`` field) of each entry.  This is useful
        for discovering which model names can be passed to the other client
        methods (e.g. ``conversation_with_model``).

        Returns
        -------
        List[str]
            The available model identifiers, e.g.
            ``["google/gemma-3-12b-it", "speakleash/Bielik-11B-v2.3-Instruct"]``.

        Raises
        ------
        LLMRouterError
            Propagated from the underlying service if the HTTP request fails
            or the response cannot be decoded as JSON.
        """
        response = ModelsService(self.http, self.logger).call_get()
        data = response.get("data", [])
        return [model["id"] for model in data]

    # ------------------------------------------------------------------ #
    def conversation_with_model(
        self,
        payload: _ConvPayload,
    ) -> Dict[str, Any]:
        """
        Call the standard conversation endpoint.

        The method accepts either a raw dictionary or a
        :class:`ConversationWithModelRequest` instance; in the latter case the
        model is serialised via ``model_dump()`` before the request is sent.

        Parameters
        ----------
        payload : Union[Dict[str, Any], ConversationWithModelRequest]
            The request body to be forwarded to ``/api/conversation_with_model``.

        Returns
        -------
        dict
            Parsed JSON response from the router.
        """
        if isinstance(payload, ConversationWithModelService.model_cls):
            payload = payload.model_dump()

        return ConversationWithModelService(self.http, self.logger).call_post(
            payload
        )

    def extended_conversation_with_model(
        self,
        payload: _ExtConvPayload,
    ) -> Dict[str, Any]:
        """
        Call the extended conversation endpoint
        that supports an explicit system prompt.

        Parameters
        ----------
        payload : Union[Dict[str, Any], ExtendedConversationWithModelRequest]
            The request body for ``/api/extended_conversation_with_model``.

        Returns
        -------
        dict
            Parsed JSON response from the router.
        """
        if isinstance(payload, ExtendedConversationWithModelService.model_cls):
            payload = payload.model_dump()
        return ExtendedConversationWithModelService(
            self.http, self.logger
        ).call_post(payload)

    # ------------------------------------------------------------------ #
    def polarity_3c(
        self,
        payload: Optional[
            Union[
                Dict[str, Any],
                Polarity3cService.model_cls,
            ]
        ] = None,
        texts: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = 0.2,
        max_new_tokens: Optional[int] = 256,
    ) -> Dict[str, Any]:
        """
        Detect 3-class polarity (ambivalent, positive, negative) for a list of texts
        using the ``/api/polarity_3c`` endpoint.

        The method can be used in three ways:

        1. **Pass a ready‑made dictionary** – ``payload`` is a ``dict`` that already
           conforms to :class:`Polarity3cModel`.
        2. **Pass a Pydantic model instance** – ``payload`` is a
           ``Polarity3cModel`` and will be serialized automatically.
        3. **Provide ``texts`` and ``model`` arguments** – the client builds a
           ``Polarity3cModel`` instance on‑the‑fly.

        If neither a payload nor the ``texts``/``model`` pair is supplied, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : Optional[Union[Dict[str, Any], Polarity3cModel]]
            Optional pre‑constructed request body.
        texts : Optional[List[str]]
            List of source strings to classify (required if ``payload`` is not
            supplied).
        model : Optional[str]
            Model identifier to be used for classification (required if ``payload``
            is not supplied).
        temperature: Optional[float]
            Temperature
        max_new_tokens: Optional[int]
            Max new tokens
        Returns
        -------
        dict
            Parsed JSON response from the polarity classification service.

        Raises
        ------
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and either ``texts`` or ``model`` is missing.
        """
        payload = self._build_payload(
            model_cls=Polarity3cService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return Polarity3cService(self.http, self.logger).call_post(payload)

    def translate(
        self,
        payload: Optional[
            Union[
                Dict[str, Any],
                TranslateService.model_cls,
            ]
        ] = None,
        texts: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = 0.75,
        max_new_tokens: Optional[int] = 512,
    ) -> Dict[str, Any]:
        """
        Translate a list of texts using the ``/api/translate`` endpoint.

        The method can be used in three ways:

        1. **Pass a ready‑made dictionary** – ``payload`` is a ``dict`` that already
           conforms to :class:`TranslateModel`.
        2. **Pass a Pydantic model instance** – ``payload`` is a
           ``TranslateModel`` and will be serialized automatically.
        3. **Provide ``texts`` and ``model`` arguments** – the client builds a
           ``TranslateModel`` instance on‑the‑fly.

        If neither a payload nor the ``texts``/``model`` pair is supplied, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : Optional[Union[Dict[str, Any], TranslateModel]]
            Optional pre‑constructed request body.
        texts : Optional[List[str]]
            List of source strings to translate (required if ``payload`` is not
            supplied).
        model : Optional[str]
            Model identifier to be used for translation (required if ``payload``
            is not supplied).
        temperature: Optional[float]
            Temperature
        max_new_tokens: Optional[int]
            Max new tokens
        Returns
        -------
        dict
            Parsed JSON response from the translation service.

        Raises
        ------
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and either ``texts`` or ``model`` is missing.
        """
        payload = self._build_payload(
            model_cls=TranslateService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return TranslateService(self.http, self.logger).call_post(payload)

    def simplify_text(
        self,
        payload: Optional[
            Union[
                Dict[str, Any],
                SimplifyTextService.model_cls,
            ]
        ] = None,
        texts: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = 0.2,
        max_new_tokens: Optional[int] = 256,
    ) -> Dict[str, Any]:
        """
        Simplify a list of texts using the ``/api/simplify_text`` endpoint.

        The method can be used in three ways:

        1. **Pass a ready‑made dictionary** – ``payload`` is a ``dict`` that already
           conforms to :class:`SimplifyTextModel`.
        2. **Pass a Pydantic model instance** – ``payload`` is a
           ``SimplifyTextModel`` and will be serialized automatically.
        3. **Provide ``texts`` and ``model`` arguments** – the client builds a
           ``SimplifyTextModel`` instance on‑the‑fly.

        If neither a payload nor the ``texts``/``model`` pair is supplied, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : Optional[Union[Dict[str, Any], SimplifyTextModel]]
            Optional pre‑constructed request body.
        texts : Optional[List[str]]
            List of source strings to simplify (required if ``payload`` is not
            supplied).
        model : Optional[str]
            Model identifier to be used for simplification (required if ``payload``
            is not supplied).
        temperature: Optional[float]
            Temperature
        max_new_tokens: Optional[int]
            Max new tokens
        Returns
        -------
        dict
            Parsed JSON response from the text‑simplification service.

        Raises
        ------
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and either ``texts`` or ``model`` is missing.
        """
        payload = self._build_payload(
            model_cls=SimplifyTextService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return SimplifyTextService(self.http, self.logger).call_post(payload)

    def generative_answer(
        self,
        payload: Optional[
            Union[
                Dict[str, Any],
                GenerativeAnswerService.model_cls,
            ]
        ] = None,
        model: Optional[str] = None,
        texts: Optional[Dict[str, List[str]] | List[str]] = None,
        question_str: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = self._build_payload(
            model_cls=GenerativeAnswerService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            question_str=question_str,
        )
        return GenerativeAnswerService(self.http, self.logger).call_post(payload)

    def generate_article_from_text(
        self,
        payload: Optional[
            Union[
                Dict[str, Any],
                GenerateArticleFromTextService.model_cls,
            ]
        ] = None,
        text: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = self._build_payload(
            model_cls=GenerateArticleFromTextService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            text=text,
        )
        return GenerateArticleFromTextService(self.http, self.logger).call_post(
            payload
        )

    def generate_article_from_texts(
        self,
        payload: Optional[
            Union[
                Dict[str, Any],
                GenerateArticleFromTextsService.model_cls,
            ]
        ] = None,
        texts: Optional[List[str]] = None,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate a short (~A4) article from multiple input texts using the
        ``/api/generate_article_from_texts`` builtin endpoint.

        Accepts a prebuilt payload dict or model instance, or a ``texts`` list.
        The client builds a payload when ``payload`` is not provided.
        """
        payload = self._build_payload(
            model_cls=GenerateArticleFromTextsService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
        )
        return GenerateArticleFromTextsService(self.http, self.logger).call_post(
            payload
        )

    def create_full_article_from_texts(
        self,
        payload: Optional[
            Union[
                Dict[str, Any],
                CreateFullArticleFromTextsService.model_cls,
            ]
        ] = None,
        user_query: Optional[str] = None,
        texts: Optional[List[str]] = None,
        article_type: Optional[str] = None,
        model: Optional[str] = None,
        max_new_tokens: Optional[int] = 1024,
    ) -> Dict[str, Any]:
        """
        Create a full article from multiple input texts using the
        ``/api/create_full_article_from_texts`` builtin endpoint.

        Accepts a prebuilt payload dict or model instance, or keyword
        arguments ``user_query`` and ``texts`` and optional ``article_type``.
        """
        payload = self._build_payload(
            model_cls=CreateFullArticleFromTextsService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            user_query=user_query,
            texts=texts,
            article_type=article_type,
            max_new_tokens=max_new_tokens,
        )
        return CreateFullArticleFromTextsService(self.http, self.logger).call_post(
            payload
        )

    def generate_questions(
        self,
        payload: Optional[
            Union[
                Dict[str, Any],
                GenerateQuestionsService.model_cls,
            ]
        ] = None,
        texts: Optional[List[str]] = None,
        number_of_questions: Optional[int] = 1,
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Generate questions from multiple input texts using the
        ``/api/generate_questions`` builtin endpoint.

        The method can be used in three ways:

        1. **Pass a ready‑made dictionary** – ``payload`` is a ``dict`` that already
           conforms to :class:`GenerateQuestionsModel`.
        2. **Pass a Pydantic model instance** – ``payload`` is a
           ``GenerateQuestionsModel`` and will be serialized automatically.
        3. **Provide ``texts`` and ``model`` arguments** – the client builds a
           ``GenerateQuestionsModel`` instance on‑the‑fly.

        If neither a payload nor the ``texts``/``model`` pair is supplied, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : Optional[Union[Dict[str, Any], GenerateQuestionsModel]]
            Optional pre‑constructed request body.
        texts : Optional[List[str]]
            List of source strings from which to generate questions (required if
            ``payload`` is not supplied).
        number_of_questions : Optional[int], default ``1``
            Desired number of questions to generate per input text.
        model : Optional[str]
            Model identifier to be used (required if ``payload`` is not supplied).

        Returns
        -------
        dict
            Parsed JSON response from the question generation service.

        Raises
        ------
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and either ``texts`` or ``model`` is missing.
        """
        payload = self._build_payload(
            model_cls=GenerateQuestionsService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            number_of_questions=number_of_questions,
        )
        return GenerateQuestionsService(self.http, self.logger).call_post(payload)

    def generate_label(
        self,
        payload: Optional[
            Union[
                Dict[str, Any],
                GenerateLabelService.model_cls,
            ]
        ] = None,
        texts: Optional[List[str]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = 0.2,
        max_new_tokens: Optional[int] = 64,
    ) -> Dict[str, Any]:
        """
        Generate a category name (label) for a list of texts using the
        ``/api/generate_label`` endpoint.

        The endpoint receives a list of related texts and returns a single,
        concise category name that best captures their common essence.

        The method can be used in three ways:

        1. **Pass a ready‑made dictionary** – ``payload`` is a ``dict`` that
           already conforms to :class:`GenerateLabelModel`.
        2. **Pass a Pydantic model instance** – ``payload`` is a
           ``GenerateLabelModel`` and will be serialized automatically.
        3. **Provide ``texts`` and ``model`` arguments** – the client builds a
           ``GenerateLabelModel`` instance on‑the‑fly.

        If neither a payload nor the ``texts``/``model`` pair is supplied, a
        :class:`NoArgsAndNoPayloadError` is raised.

        Parameters
        ----------
        payload : Optional[Union[Dict[str, Any], GenerateLabelModel]]
            Optional pre‑constructed request body.
        texts : Optional[List[str]]
            List of related source strings whose shared essence should be
            captured by a single category name (required if ``payload`` is not
            supplied).
        model : Optional[str]
            Model identifier to be used (required if ``payload`` is not
            supplied).
        temperature : Optional[float], default ``0.2``
            Sampling temperature; kept low for a deterministic label.
        max_new_tokens : Optional[int], default ``64``
            Maximum number of tokens for the generated label.

        Returns
        -------
        dict
            Parsed JSON response from the label‑generation service.

        Raises
        ------
        NoArgsAndNoPayloadError
            If ``payload`` is ``None`` and either ``texts`` or ``model`` is
            missing.
        """
        payload = self._build_payload(
            model_cls=GenerateLabelService.model_cls,
            payload_arg=payload,
            model_name=model or self.default_model,
            texts=texts,
            temperature=temperature,
            max_new_tokens=max_new_tokens,
        )
        return GenerateLabelService(self.http, self.logger).call_post(payload)

    # ------------------------------------------------------------------ #
    @staticmethod
    def _build_payload(
        *,
        model_cls: type | None,
        payload_arg: Any,
        **extra: Any,
    ) -> Dict[str, Any]:
        """
        Normalize a payload to a ``dict``.

        Handles three input shapes and builds from keyword arguments when the
        caller passed individual parameters instead of a pre‑constructed payload:

        1. **Pydantic model instance** → serialised via ``model_dump()``.
        2. **Dict** → returned unchanged.
        3. **None** → constructed from *extra* keyword arguments using the
           provided *model_cls*; raises :class:`NoArgsAndNoPayloadError` if
           required keys are missing.
        """
        if isinstance(payload_arg, BaseModel):
            return payload_arg.model_dump()

        if isinstance(payload_arg, Dict):
            return payload_arg

        # Neither a model nor a dict — build from named parameters.
        if model_cls is not None and extra:
            return model_cls(**extra).model_dump()

        raise NoArgsAndNoPayloadError("No payload and no arguments were passed!")
