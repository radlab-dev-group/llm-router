"""
Utility endpoints that expose built‑in generative capabilities.

Each endpoint validates its input via a pydantic model, forwards the request to
the generic ``EndpointWithHttpRequestI`` machinery, and post‑processes the
response into a clean JSON payload.
"""

import os
import re
from contextvars import ContextVar

from typing import Any, Dict, List, Optional

from rdl_ml_utils.handlers.prompt_handler import PromptHandler

from llm_router_lib.data_models.builtin_utils import (
    GenerateQuestionsModel,
    GENERATE_QUESTIONS_REQ,
    GENERATE_QUESTIONS_OPT,
    GenerateArticleFromTextModel,
    GENERATE_ARTICLE_FROM_TEXT_REQ,
    GENERATE_ARTICLE_FROM_TEXT_OPT,
    TRANSLATE_TEXT_REQ,
    TRANSLATE_TEXT_OPT,
    TranslateModel,
    POLARITY_3C_REQ,
    POLARITY_3C_OPT,
    Polarity3cModel,
    SIMPLIFY_TEXT_REQ,
    SIMPLIFY_TEXT_OPT,
    SimplifyTextModel,
    CreateFullArticleFromTextsModel,
    CREATE_FULL_ARTICLE_FROM_TEXTS_REQ,
    CREATE_FULL_ARTICLE_FROM_TEXTS_OPT,
    GENERATIVE_ANSWER_REQ,
    GENERATIVE_ANSWER_OPT,
    GenerativeAnswerModel,
    RewriteQueryModel,
    REWRITE_QUERY_REQ,
    REWRITE_QUERY_OPT,
    GenerateArticleFromTextsModel,
    GENERATE_ARTICLE_FROM_TEXTS_REQ,
    GENERATE_ARTICLE_FROM_TEXTS_OPT,
    GenerateLabelModel,
    GENERATE_LABEL_REQ,
    GENERATE_LABEL_OPT,
)
from llm_router_api.core.decorators import EP
from llm_router_api.core.model_handler import ModelHandler
from llm_router_api.base.constants import REST_API_LOG_LEVEL
from llm_router_api.endpoints.endpoint_i import EndpointWithHttpRequestI


class ApiVersion(EndpointWithHttpRequestI):
    """
    Endpoint that returns the router version.

    Registered at ``/api/version`` — ``dont_add_api_prefix`` is ``False``, so
    ``LLM_ROUTER_EP_PREFIX`` (``/api`` by default) is prepended; this is the path
    ``llm_router_lib`` clients call.
    Auth: **not public by default** — the default
    ``LLM_ROUTER_AUTH_PUBLIC_ENDPOINTS`` lists the bare ``/version``, which does not
    match ``/api/version``; add the prefixed path there for an unauthenticated probe.
    """

    VERSION_FILE = ".version"

    EP_DONT_NEED_GUARDRAIL_AND_MASKING = True

    REQUIRED_ARGS = []
    OPTIONAL_ARGS = []
    SYSTEM_PROMPT_NAME = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        model_handler: Optional[ModelHandler] = None,
        prompt_handler: Optional[PromptHandler] = None,
        ep_name: str = "version",
    ):
        """
        Create a health‑check endpoint that returns the router version.

        Parameters
        ----------
        logger_file_name : Optional[str]
            Optional file name for the logger.
        logger_level : Optional[str]
            Logging verbosity; defaults to :data:`REST_API_LOG_LEVEL`.
        model_handler : Optional[ModelHandler]
            Unused for this endpoint but required by the base class.
        prompt_handler : Optional[PromptHandler]
            Unused for this endpoint but required by the base class.
        ep_name : str
            URL fragment for the endpoint (default ``"version"``).
        """
        super().__init__(
            method="GET",
            ep_name=ep_name,
            logger_file_name=logger_file_name,
            logger_level=logger_level,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            api_types=[
                "builtin",
                "ollama",
                "vllm",
                "openai",
                "llmstudio",
                "anthropic",
            ],
        )

        self.version = "not-given"
        if os.path.exists(self.VERSION_FILE):
            try:
                with open(self.VERSION_FILE, encoding="utf-8") as f:
                    self.version = f.read().strip()
                    if not re.fullmatch(
                        r"\d+\.\d+\.\d+(?:-[A-Za-z]+\d*)?", self.version
                    ):
                        raise ValueError(
                            f"Invalid version format: '{self.version}'. "
                            f"Expected format X.X.Y or X.X.Y-suffix "
                            f"(e.g., 0.5.2, 1.0.2rc, 1.0.0-rc1)"
                        )
            except Exception as e:
                raise e

        self.logger.info(f"  -> Running LLM-Router version: {self.version}")

    @EP.response_time
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any] | str]:
        """
        Return the router version as a JSON payload.

        The method sets ``direct_return`` so that the Flask registrar sends the
        dictionary directly without additional wrapping.

        Returns
        -------
        Dict
            ``{"version": "<semver>"}``.
        """
        self.direct_return = True
        return {"version": self.version}


class TextListUtilityEndpoint(EndpointWithHttpRequestI):
    """
    Shared base class for the builtin ``texts`` utility endpoints.

    Every endpoint built on this class follows the same contract:

    * it accepts a list of ``texts`` together with generation options;
    * it runs with ``call_for_each_user_msg=True`` (one ``user`` message per
      source text);
    * it returns ``{"response": [...], "generation_time": <seconds>}``.

    Subclasses only need to supply the endpoint‑specific pieces:

    * ``ep_name`` (the URL fragment),
    * ``REQUIRED_ARGS`` / ``OPTIONAL_ARGS`` / ``SYSTEM_PROMPT_NAME``,
    * :attr:`MODEL_CLS` – the pydantic request model, and
    * the :meth:`_build_results` hook that turns the per‑text raw model outputs
      into the final ``response`` list.

    Endpoints that must inject a ``map_prompt`` (e.g. ``GenerateQuestions``)
    override :meth:`build_map_prompt`.
    """

    #: Subclasses must point this at their pydantic request model.
    MODEL_CLS = None

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "",
    ):
        """
        Initialize a text‑list utility endpoint.

        All wiring shared by the ``texts`` endpoints (``builtin`` api type,
        ``POST`` method, ``call_for_each_user_msg=True``) is configured here;
        subclasses only pass their own default ``ep_name``.
        """
        if not self.MODEL_CLS:
            raise TypeError(
                f"{type(self).__name__} must define a MODEL_CLS attribute"
            )
        super().__init__(
            ep_name=ep_name,
            api_types=["builtin"],
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            direct_return=False,
            call_for_each_user_msg=True,
        )
        self._prepare_response_function = self._prepare_response

    # ------------------------------------------------------------------ #
    # Payload
    # ------------------------------------------------------------------ #
    def build_map_prompt(self, payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        Hook for injecting a ``map_prompt`` mapping into the payload.

        The default returns ``None`` (no ``map_prompt`` is added).  Subclasses
        that need to template system‑prompt placeholders override this and
        return the mapping to store under ``payload["map_prompt"]``.
        """
        return None

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Validate the input against :attr:`MODEL_CLS` and build the request payload.

        The payload contains a ``model`` field, an optional ``stream`` flag and a
        list of ``user`` messages – one per source text.  The raw ``texts`` list
        is removed from the payload.

        Returns
        -------
        Dict
            Normalised payload for the downstream service.
        """
        options = self.MODEL_CLS(**params)
        _payload = options.model_dump()
        _payload["stream"] = _payload.get("stream", False)
        _payload["model"] = _payload["model_name"]
        _payload["messages"] = [
            {"role": "user", "content": _t} for _t in _payload["texts"]
        ]
        _payload.pop("texts")

        map_prompt = self.build_map_prompt(_payload)
        if map_prompt is not None:
            _payload["map_prompt"] = map_prompt

        return _payload

    # ------------------------------------------------------------------ #
    # Response
    # ------------------------------------------------------------------ #
    def _build_results(self, raw_texts: List[str], contents: List[str]) -> List[Any]:
        """
        Build the final ``response`` list from the per‑text model outputs.

        Parameters
        ----------
        raw_texts : List[str]
            Raw assistant output for each source text (in input order).
        contents : List[str]
            The original source texts (in input order).
        """
        raise NotImplementedError

    def _prepare_response(self, responses: List[Any], contents: List[str]):
        """
        Collate the per‑text model outputs and report the elapsed time.

        Parameters
        ----------
        responses : List[requests.Response]
            Responses from the model service.
        contents : List[str]
            Original source texts.

        Returns
        -------
        Dict
            ``{"response": <list>, "generation_time": <seconds>}``.
        """
        assert len(responses) == len(contents)
        raw_texts = [
            self._get_choices_from_response(response=response)[2]
            for response in responses
        ]
        results = self._build_results(raw_texts, contents)
        return {
            "response": results,
            "generation_time": self._generation_time(),
        }


class GenerateQuestions(TextListUtilityEndpoint):
    """
    Built‑in utility: generate questions from input texts.

    Registered at ``/api/generate_questions`` (with default prefix).
    Auth: **optional** — required only when
    ``LLM_ROUTER_AUTH_ENABLED=true`` (``builtin`` permission).
    """

    MODEL_CLS = GenerateQuestionsModel
    REQUIRED_ARGS = GENERATE_QUESTIONS_REQ
    OPTIONAL_ARGS = GENERATE_QUESTIONS_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/generate-questions",
        "en": "builtin/system/en/generate-questions",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "generate_questions",
    ):
        """
        Initialize the “generate questions” endpoint.
        """
        super().__init__(
            logger_file_name=logger_file_name,
            logger_level=logger_level,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            ep_name=ep_name,
        )

    def build_map_prompt(self, payload: Dict[str, Any]) -> Dict[str, str]:
        """Inject the question‑count placeholder used by the system prompt."""
        return {
            "##QUESTION_NUM_STR##": f"{payload['number_of_questions']} question(s)",
        }

    def _build_results(self, raw_texts: List[str], contents: List[str]):
        """Post‑process the raw per‑text outputs into the final question lists."""
        questions: List[List[str]] = []
        for raw in raw_texts:
            dialog_question = raw.strip().split("\n\n")[-1]
            questions.append([q.strip() for q in dialog_question.split("\n")])

        proper_texts_questions = self._prepare_proper_question_str(questions)
        return self._prepare_response_for_generated_questions(
            texts=contents, proper_texts_questions=proper_texts_questions
        )

    def _prepare_proper_question_str(
        self, questions: List[List[str]], split_with_question_mark: bool = False
    ) -> List[List[str]]:
        """
        Clean up the generated questions (strip enumeration, optional split).
        """
        proper_texts_questions = []
        for text_questions in questions:
            new_text_questions = []
            for question in text_questions:
                text_q = question.strip()
                if not text_q:
                    continue
                if split_with_question_mark and "?" in text_q:
                    for spl_q in text_q.split("?"):
                        proper_q = self._remove_enumeration_from_question(spl_q)
                        proper_q = proper_q.strip()
                        if not proper_q:
                            continue
                        new_text_questions.append(proper_q + "?")
                else:
                    new_text_questions.append(
                        self._remove_enumeration_from_question(text_q)
                    )
            new_text_questions = [
                q.strip() for q in new_text_questions if len(q.strip())
            ]
            proper_texts_questions.append(new_text_questions)
        return proper_texts_questions

    @staticmethod
    def _remove_enumeration_from_question(question_str: str):
        """Drop a leading ``1.``‑style enumeration prefix from a question."""
        question_str = question_str.strip()
        dot_pos = question_str.find(".")
        if dot_pos == -1:
            return question_str

        q_number = question_str[:dot_pos]
        try:
            _ = int(q_number)
            question_str = question_str[dot_pos + 1 :]
        except Exception:
            # intentional: a non-numeric prefix is not a numbered question —
            # keep the original string unchanged.
            pass
        return question_str

    @staticmethod
    def _prepare_response_for_generated_questions(
        texts: List[str], proper_texts_questions: List[List[str]]
    ) -> List[Dict[str, List[List[str]]]]:
        """Pair each source text with its cleaned question list."""
        response = []
        for txt, questions in zip(texts, proper_texts_questions):
            response_body = {"text": txt, "questions": questions}
            response.append(response_body)
        return response


class Polarity3c(TextListUtilityEndpoint):
    """
    Built‑in utility: detect polarity (ambivalent, positive, negative) for input texts.

    Registered at ``/api/polarity_3c`` (with default prefix).
    Auth: **optional** — required only when
    ``LLM_ROUTER_AUTH_ENABLED=true`` (``builtin`` permission).
    """

    MODEL_CLS = Polarity3cModel
    REQUIRED_ARGS = POLARITY_3C_REQ
    OPTIONAL_ARGS = POLARITY_3C_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/polarity-3c",
        "en": "builtin/system/en/polarity-3c",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "polarity_3c",
    ):
        """
        Initialize the polarity 3‑class classification endpoint.
        """
        super().__init__(
            logger_file_name=logger_file_name,
            logger_level=logger_level,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            ep_name=ep_name,
        )

    @staticmethod
    def _extract_polarity(raw_output: str) -> str:
        """
        Extract and normalise the polarity class from raw model output.
        """
        cleaned = raw_output.strip().lower()
        if cleaned in {"positive", "negative", "ambivalent"}:
            return cleaned
        match = re.search(r"\b(positive|negative|ambivalent)\b", cleaned)
        if match:
            return match.group(1)
        return cleaned

    def _build_results(self, raw_texts: List[str], contents: List[str]):
        """Pair each original text with its detected polarity."""
        return [
            {"original": orig_text, "polarity": self._extract_polarity(raw)}
            for raw, orig_text in zip(raw_texts, contents)
        ]


class Translate(TextListUtilityEndpoint):
    """
    Built‑in utility: translate a list of texts.

    Registered at ``/api/translate`` (with default prefix).
    Auth: **optional** — required only when
    ``LLM_ROUTER_AUTH_ENABLED=true`` (``builtin`` permission).
    """

    MODEL_CLS = TranslateModel
    REQUIRED_ARGS = TRANSLATE_TEXT_REQ
    OPTIONAL_ARGS = TRANSLATE_TEXT_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/translate-to-pl",
        "en": "builtin/system/en/translate-to-pl",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "translate",
    ):
        """
        Initialize the translation endpoint.
        """
        super().__init__(
            logger_file_name=logger_file_name,
            logger_level=logger_level,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            ep_name=ep_name,
        )

    def _build_results(self, raw_texts: List[str], contents: List[str]):
        """Pair each original text with its translation."""
        return [
            {"original": orig_text, "translated": raw}
            for raw, orig_text in zip(raw_texts, contents)
        ]


class SimplifyText(TextListUtilityEndpoint):
    """
    Built‑in utility: simplify input texts.

    Registered at ``/api/simplify_text`` (with default prefix).
    Auth: **optional** — required only when
    ``LLM_ROUTER_AUTH_ENABLED=true`` (``builtin`` permission).
    """

    MODEL_CLS = SimplifyTextModel
    REQUIRED_ARGS = SIMPLIFY_TEXT_REQ
    OPTIONAL_ARGS = SIMPLIFY_TEXT_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/simplify-text",
        "en": "builtin/system/en/simplify-text",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "simplify_text",
    ):
        """
        Initialize the text‑simplification endpoint.
        """
        super().__init__(
            logger_file_name=logger_file_name,
            logger_level=logger_level,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            ep_name=ep_name,
        )

    def _build_results(self, raw_texts: List[str], contents: List[str]):
        """Return the simplified versions of the original texts."""
        return list(raw_texts)


class GenerateArticleFromText(EndpointWithHttpRequestI):
    """
    Built‑in utility: generate a short article from a single text.

    Registered at ``/api/generate_article_from_text`` (with default prefix).
    Auth: **optional** — required only when
    ``LLM_ROUTER_AUTH_ENABLED=true`` (``builtin`` permission).
    """

    REQUIRED_ARGS = GENERATE_ARTICLE_FROM_TEXT_REQ
    OPTIONAL_ARGS = GENERATE_ARTICLE_FROM_TEXT_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/news-on-sm",
        "en": "builtin/system/en/news-on-sm",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "generate_article_from_text",
    ):
        """
        Initialize the news‑generation endpoint.
        """
        super().__init__(
            ep_name=ep_name,
            api_types=["builtin"],
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            direct_return=False,
            call_for_each_user_msg=False,
        )

        self._prepare_response_function = self.__prepare_response_function

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Convert the incoming request into a payload
        that asks the model to write a news article.

        Returns
        -------
        Dict
            Normalised payload for the downstream model.
        """
        options = GenerateArticleFromTextModel(**params)
        _payload = options.model_dump()
        _payload["stream"] = _payload.get("stream", False)
        _payload["model"] = _payload["model_name"]
        _payload["messages"] = [
            {
                "role": "user",
                "content": _payload["text"],
            },
        ]
        return _payload

    def __prepare_response_function(self, response):
        """
        Extract the generated article text and report processing time.

        Parameters
        ----------
        response : requests.Response
            Raw response from the model service.

        Returns
        -------
        Dict
            ``{"response": {"article_text": <text>}, "generation_time": <seconds>}``.
        """
        _, choices, _assistant_response = self._get_choices_from_response(
            response=response
        )

        return {
            "response": {
                "article_text": choices[0].get("message", {}).get("content")
            },
            "generation_time": self._generation_time(),
        }


class CreateFullArticleFromTexts(GenerateArticleFromText):
    """
    Built‑in utility: generate a full article from multiple texts.

    Registered at ``/api/create_full_article_from_texts`` (with default prefix).
    Auth: **optional** — required only when ``LLM_ROUTER_AUTH_ENABLED=true``
    (``builtin`` permission) — inherits policy from
    :class:`GenerateArticleFromText`.
    """

    REQUIRED_ARGS = CREATE_FULL_ARTICLE_FROM_TEXTS_REQ
    OPTIONAL_ARGS = CREATE_FULL_ARTICLE_FROM_TEXTS_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/full-article",
        "en": "builtin/system/en/full-article",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "create_full_article_from_texts",
    ):
        """
        Initialize the “full article” endpoint, extending the basic news generator.
        """
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
        )

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Build a payload that combines multiple source texts into a single article.

        The method also injects optional prompt mapping and postfix strings
        used by the model’s system prompt.

        Returns
        -------
        Dict
            Normalised request payload.
        """
        options = CreateFullArticleFromTextsModel(**params)
        _payload = options.model_dump()

        map_prompt = {
            "##USER_Q_STR##": _payload["user_query"],
        }
        prompt_str_postfix = _payload.get("article_type")

        user_texts_str = "\n\n".join(
            t.strip() for t in _payload["texts"] if len(t.strip())
        )

        _payload["stream"] = _payload.get("stream", False)
        _payload["model"] = _payload["model_name"]
        _payload["messages"] = [
            {
                "role": "user",
                "content": user_texts_str,
            }
        ]
        _payload.pop("texts")
        _payload.pop("user_query")
        _payload.pop("article_type")

        _payload["map_prompt"] = map_prompt
        _payload["prompt_str_postfix"] = prompt_str_postfix

        return _payload


class GenerateArticleFromTexts(CreateFullArticleFromTexts):
    """
    Built‑in utility: generate a concise A4‑length article summarising the
    provided texts/news from a single day. Registered at
    ``/api/generate_article_from_texts``.
    """

    REQUIRED_ARGS = GENERATE_ARTICLE_FROM_TEXTS_REQ
    OPTIONAL_ARGS = GENERATE_ARTICLE_FROM_TEXTS_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/article-from-texts",
        "en": "builtin/system/en/article-from-texts",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "generate_article_from_texts",
    ):
        super().__init__(
            logger_file_name=logger_file_name,
            logger_level=logger_level,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            ep_name=ep_name,
        )

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Build a payload that concatenates multiple source texts into a single
        user message. The model should return a short (~A4) article in Polish.
        """
        options = GenerateArticleFromTextsModel(**params)
        _payload = options.model_dump()

        user_texts_str = "\n\n".join(
            t.strip() for t in _payload["texts"] if len(t.strip())
        )

        _payload["stream"] = _payload.get("stream", False)
        _payload["model"] = _payload["model_name"]
        _payload["messages"] = [
            {
                "role": "user",
                "content": user_texts_str,
            }
        ]
        _payload.pop("texts")

        return _payload


# ----------------------------------------------------------------------
# Per-request numbered context (RAG citations) for ``GenerativeAnswer``.
#
# ``prepare_payload`` knows the supplied fragments, but the response
# function is called by the shared HTTP layer with only the model's
# response (see ``EndpointWithHttpRequestI.return_http_response``), so the
# fragments cannot be handed over through its signature.  The endpoint
# object is a singleton shared by every concurrent request, so keeping the
# fragments on ``self`` would let one request answer with another's
# citations; a ContextVar scopes the value per request, exactly like
# ``_request_start_time`` in ``llm_router_api.endpoints.endpoint_i``.
# ``None`` means "this request is not in numbered-citation mode".
# ----------------------------------------------------------------------
_numbered_citation_context: "ContextVar[Optional[List[Dict[str, Any]]]]" = (
    ContextVar("llm_router_numbered_citation_context", default=None)
)


def _conversation_messages(
    history: List[Dict[str, str]],
) -> List[Dict[str, str]]:
    """Flatten chronological ``{user, assistant}`` turns into chat messages.

    Both the answer endpoint and the query rewriter take history as complete
    turns, so that a partial exchange can never slip in and a ``system`` role
    cannot be smuggled through the history (the model rejects those shapes).
    """
    return [
        {"role": role, "content": turn[role]}
        for turn in history
        for role in ("user", "assistant")
    ]


def _require_known_citations(
    answer: Optional[str], documents: List[Dict[str, Any]]
) -> None:
    """Reject an answer citing fragment numbers that were never supplied.

    A model inventing ``[99]`` would otherwise hand back a citation the caller
    cannot resolve, which looks like a grounded answer but is not one.
    """
    referenced = {int(n) for n in re.findall(r"\[(\d+)\]", answer or "")}
    unknown = referenced - {document["n"] for document in documents}
    if unknown:
        raise ValueError(f"Unknown numeric citation references: {sorted(unknown)}")


class GenerativeAnswer(GenerateArticleFromText):
    """
    Built‑in utility: answer a question using provided context.

    Registered at ``/api/generative_answer`` (with default prefix).
    Auth: **optional** — required only when ``LLM_ROUTER_AUTH_ENABLED=true``
    (``builtin`` permission) — inherits policy from
    :class:`GenerateArticleFromText`.
    """

    REQUIRED_ARGS = GENERATIVE_ANSWER_REQ
    OPTIONAL_ARGS = GENERATIVE_ANSWER_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/answer-from-context-simple",
        "en": "builtin/system/en/answer-from-context-simple",
    }
    SYSTEM_PROMPT_WITH_ENUMERATED_DOCUMENTS_NAME = {
        "pl": "builtin/system/pl/answer-from-context-with-citations",
        "en": "builtin/system/en/answer-from-context-with-citations",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "generative_answer",
    ):
        """
        Initialize the context‑aware answer endpoint.
        """
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
        )

        self._prepare_response_function = self.__prepare_response_function

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Assemble a payload that provides the model with a context and a question.

        The method concatenates all supplied texts (optionally prefixing each
        with its document name), injects prompt mapping, and prepares optional
        forced or postfix system prompts.

        Returns
        -------
        Dict
            Normalised request payload for the downstream model.
        """
        options = GenerativeAnswerModel(**params)
        _payload = options.model_dump()
        _payload["stream"] = _payload.get("stream", False)
        _payload["model"] = _payload["model_name"]

        map_prompt = {
            "##QUESTION_STR##": _payload["question_str"],
        }
        prompt_str_postfix = _payload.get("question_prompt")
        prompt_str_force = _payload.get("system_prompt")

        documents = _payload.pop("enumerated_documents")
        numbered = _payload.pop("system_prompt_with_enumerated_documents")
        # Read back by ``__prepare_response_function`` through the per-request
        # ContextVar: the response function is called with the model response
        # only, so the fragments cannot travel through its signature.
        _numbered_citation_context.set(documents if numbered else None)

        if numbered:
            context = self._numbered_context_text(documents)
            # The citation instructions become the forced system prompt, so the
            # caller's own prompt has to move to the postfix instead.
            prompt_str_postfix = (
                "\n\n".join(
                    part for part in (prompt_str_force, prompt_str_postfix) if part
                )
                or None
            )
            prompt_str_force = self._citation_system_prompt(options.language)
        else:
            context = self._plain_context_text(
                _payload["texts"], _payload.get("doc_name_in_answer", False)
            )

        history = _payload.pop("historical_messages")
        _payload["messages"] = _conversation_messages(history)
        context = context.strip()
        if history:
            context += f"\n\nQuestion: {_payload['question_str']}"
        _payload["messages"].append({"role": "user", "content": context})
        _payload.pop("texts")
        _payload.pop("question_str")
        _payload.pop("system_prompt")
        _payload.pop("question_prompt")

        _payload["map_prompt"] = map_prompt
        _payload["prompt_str_force"] = prompt_str_force
        _payload["prompt_str_postfix"] = prompt_str_postfix

        return _payload

    def __prepare_response_function(self, response):
        """
        Return the answer extracted from the model’s response.

        Parameters
        ----------
        response : requests.Response
            Raw response from the model service.

        Returns
        -------
        Dict
            ``{"response": <answer_text>, "generation_time": <seconds>}``.
        """
        _, choices, _assistant_response = self._get_choices_from_response(
            response=response
        )

        answer = choices[0].get("message", {}).get("content")
        result = {"response": answer, "generation_time": self._generation_time()}
        documents = _numbered_citation_context.get()
        if documents is not None:
            _require_known_citations(answer, documents)
            result["citations"] = documents
        return result

    # ---- context / prompt builders ---------------------------------------- #
    @staticmethod
    def _numbered_context_text(documents: List[Dict[str, Any]]) -> str:
        """Render the numbered fragments as ``[n]`` blocks, in supplied order."""
        return "\n\n".join(
            f"[{document['n']}] Document name: {document['document_name']}"
            + (
                f"; Page number: {document['page_number']}"
                if document.get("page_number") is not None
                else ""
            )
            + "\n"
            f"Document context: {document['text_str']}"
            for document in documents
        )

    @staticmethod
    def _plain_context_text(texts: Any, doc_name_in_answer: bool) -> str:
        """Concatenate the legacy ``texts`` passages (optionally named)."""
        if isinstance(texts, dict):
            passages = [
                (
                    f"Document name: {doc_name}\nDocument context: {text}"
                    if doc_name_in_answer
                    else text
                )
                for doc_name, group in texts.items()
                for text in group
            ]
        else:
            passages = list(texts or [])
        return "".join(f"{text}\n\n" for text in passages)

    def _citation_system_prompt(self, language: str) -> Optional[str]:
        """Citation instructions, or ``None`` when this endpoint prompts them.

        ``GenerativeAnswerWithCitations`` already resolves the citation prompt
        through :attr:`SYSTEM_PROMPT_NAME`, so forcing it again would load and
        discard the very same text.
        """
        if (
            self.SYSTEM_PROMPT_NAME
            == self.SYSTEM_PROMPT_WITH_ENUMERATED_DOCUMENTS_NAME
        ):
            return None
        if not self._prompt_handler:
            return None
        return self._prompt_handler.get_prompt(
            self.SYSTEM_PROMPT_WITH_ENUMERATED_DOCUMENTS_NAME[language]
        )


class GenerativeAnswerWithCitations(GenerativeAnswer):
    """Generate a grounded answer at ``/api/generative_answer_with_citations``.

    Uses the shared context builder and response validator, always requiring
    explicit document numbers. Auth follows the ``builtin`` permission policy.
    """

    REQUIRED_ARGS = GENERATIVE_ANSWER_REQ + ["enumerated_documents"]
    SYSTEM_PROMPT_NAME = (
        GenerativeAnswer.SYSTEM_PROMPT_WITH_ENUMERATED_DOCUMENTS_NAME
    )

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "generative_answer_with_citations",
    ):
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
        )

    @EP.require_params
    def prepare_payload(self, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return super().prepare_payload(
            dict(params, system_prompt_with_enumerated_documents=True)
        )


class RewriteQuery(GenerateArticleFromText):
    """Rewrite the last statement into a standalone retrieval query.

    Registered at ``/api/rewrite_query`` with the ``builtin`` auth permission.
    History contains complete ``{user, assistant}`` turns in chronological order.
    """

    REQUIRED_ARGS = REWRITE_QUERY_REQ
    OPTIONAL_ARGS = REWRITE_QUERY_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/rewrite-query",
        "en": "builtin/system/en/rewrite-query",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "rewrite_query",
    ):
        super().__init__(
            ep_name=ep_name,
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
        )
        self._prepare_response_function = self.__prepare_response_function

    @EP.require_params
    def prepare_payload(self, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        options = RewriteQueryModel(**params)
        payload = options.model_dump()
        payload["model"] = payload["model_name"]
        payload["stream"] = False
        payload["messages"] = _conversation_messages(
            payload.pop("historical_messages")
        )
        payload["messages"].append(
            {"role": "user", "content": payload.pop("user_last_statement")}
        )
        return payload

    def __prepare_response_function(self, response):
        _, _, answer = self._get_choices_from_response(response=response)
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("The model returned an empty rewritten query")
        return {
            "rewritten_query": answer.strip(),
            "generation_time": self._generation_time(),
        }


class GenerateLabel(EndpointWithHttpRequestI):
    """
    Built‑in utility: generate a category name (label) from input texts.

    The endpoint receives a list of related texts and asks the model to
    propose a single, concise category name that best captures their common
    essence.  All texts are combined into one user message and a single label
    is returned.

    Registered at ``/api/generate_label`` (with default prefix).
    Auth: **optional** — required only when
    ``LLM_ROUTER_AUTH_ENABLED=true`` (``builtin`` permission).
    """

    REQUIRED_ARGS = GENERATE_LABEL_REQ
    OPTIONAL_ARGS = GENERATE_LABEL_OPT
    SYSTEM_PROMPT_NAME = {
        "pl": "builtin/system/pl/generate-label",
        "en": "builtin/system/en/generate-label",
    }

    def __init__(
        self,
        logger_file_name: Optional[str] = None,
        logger_level: Optional[str] = REST_API_LOG_LEVEL,
        prompt_handler: Optional[PromptHandler] = None,
        model_handler: Optional[ModelHandler] = None,
        ep_name: str = "generate_label",
    ):
        """
        Initialize the category‑label generation endpoint.

        Parameters
        ----------
        logger_file_name : Optional[str]
            Path to a log file; falls back to the library default when ``None``.
        logger_level : Optional[str]
            Logging verbosity (e.g. ``"INFO"``, ``"DEBUG"``).  Defaults to
            :data:`REST_API_LOG_LEVEL`.
        prompt_handler : Optional[PromptHandler]
            Handler used to fetch the system‑prompt template.
        model_handler : Optional[ModelHandler]
            Handler that resolves model identifiers.
        ep_name : str
            URL fragment used when registering the Flask route
            (default ``"generate_label"``).
        """
        super().__init__(
            ep_name=ep_name,
            api_types=["builtin"],
            method="POST",
            logger_level=logger_level,
            logger_file_name=logger_file_name,
            prompt_handler=prompt_handler,
            model_handler=model_handler,
            dont_add_api_prefix=False,
            direct_return=False,
            call_for_each_user_msg=False,
        )

        self._prepare_response_function = self.__prepare_response_function

    @EP.require_params
    def prepare_payload(
        self, params: Optional[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """
        Validate input and build a payload that asks the model to name the
        category of the supplied texts.

        All source texts are concatenated into a single ``user`` message so
        that the model returns one label describing the shared essence.

        Returns
        -------
        Dict
            Normalised payload ready for the downstream model.
        """
        options = GenerateLabelModel(**params)
        _payload = options.model_dump()

        user_texts_str = "\n\n".join(
            t.strip() for t in _payload["texts"] if len(t.strip())
        )

        _payload["stream"] = _payload.get("stream", False)
        _payload["model"] = _payload["model_name"]
        _payload["messages"] = [
            {
                "role": "user",
                "content": user_texts_str,
            }
        ]
        _payload.pop("texts")

        return _payload

    @staticmethod
    def _clean_label(raw_output: Optional[str]) -> str:
        """
        Normalise the raw model output into a clean category label.

        Strips surrounding whitespace, removes wrapping quotation marks, and
        drops trailing punctuation that the model may add even though the
        prompt forbids it, leaving only the category name itself.
        """
        if not raw_output:
            return ""

        label = raw_output.strip()

        # Quotation-mark pairs (opening, closing) that may wrap the label.
        quote_pairs = (
            (chr(34), chr(34)),  # straight double quotes
            (chr(39), chr(39)),  # straight single quotes
            (chr(0x201C), chr(0x201D)),  # English double curly quotes
            (chr(0x2018), chr(0x2019)),  # English single curly quotes
            (chr(0x201E), chr(0x201C)),  # Polish/German double quotes
            (chr(0x201A), chr(0x2018)),  # Polish/German single quotes
        )

        changed = True
        while changed:
            changed = False
            # Remove one layer of surrounding quotation marks.
            for open_q, close_q in quote_pairs:
                if (
                    len(label) >= len(open_q) + len(close_q)
                    and label.startswith(open_q)
                    and label.endswith(close_q)
                ):
                    label = label[len(open_q) : -len(close_q)].strip()
                    changed = True
                    break
            # Drop one trailing period/full stop that may be tacked on.
            if label.endswith("."):
                label = label[:-1].rstrip()
                changed = True

        return label.strip()

    def __prepare_response_function(self, response):
        """
        Extract the generated category label and report processing time.

        Parameters
        ----------
        response : requests.Response
            Raw response from the model service.

        Returns
        -------
        Dict
            ``{"response": <label_text>, "generation_time": <seconds>}``.
        """
        _, choices, _assistant_response = self._get_choices_from_response(
            response=response
        )

        return {
            "response": self._clean_label(
                choices[0].get("message", {}).get("content")
            ),
            "generation_time": self._generation_time(),
        }
