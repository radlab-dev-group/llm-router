"""
Typed response models for the :class:`~llm_router_lib.client.LLMRouterClient`.

Each method of :class:`~llm_router_lib.client.LLMRouterClient` validates the
raw ``dict`` returned by the underlying service against one of the models
defined here and returns a typed instance.  This means callers always work with
a well‑structured, validated object instead of a free‑form ``dict``.

The models are intentionally tolerant:

* fields that are not strictly required by the API carry sensible defaults
  (``None`` / ``[]`` / empty nested model), and
* unknown top‑level keys (for example a ``status`` envelope) are ignored.

as a result, partial responses, or extra book‑keeping keys added by the server,
do not rise during validation.
"""

from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ----------------------------------------------------------------------
# Base classes
# ----------------------------------------------------------------------
class BaseResponse(BaseModel):
    """
    Common base for every router response model.

    ``extra`` keys are ignored (the pydantic default) so that additional keys
    added by the server do not break validation.
    """

    model_config = ConfigDict(extra="ignore")


class GenerationResponse(BaseResponse):
    """
    Base for the built‑in *generation* endpoints.

    Every generation endpoint returns an endpoint‑specific ``response`` payload
    together with a ``generation_time`` (seconds).  Concrete subclasses
    declare the type of ``response``.

    Attributes
    ----------
    generation_time : Optional[float]
        Seconds the server took to produce the response.
    """

    generation_time: Optional[float] = None


# ----------------------------------------------------------------------
# Health / meta endpoints
# ----------------------------------------------------------------------
class PingResponse(BaseResponse):
    """
    Response for ``/api/ping``.

    Shape::

        {"status": true, "body": "pong"}
    """

    status: bool = True
    body: Optional[str] = None


class VersionResponse(BaseResponse):
    """
    Response for ``/api/version``.

    Shape::

        {"version": "<semver>"}
    """

    version: str = ""


class ModelInfo(BaseResponse):
    """
    A single entry in the OpenAI‑compatible ``/v1/models`` list.
    """

    id: str
    object: Optional[str] = None
    created: Optional[float] = None
    owned_by: Optional[str] = None


class ModelsListResponse(BaseResponse):
    """
    Response for ``/v1/models``.

    Shape::

        {"object": "list", "data": [{"id", "object", "created", "owned_by"}]}

    Attributes
    ----------
    ids : List[str]
        Convenience property exposing only the ``id`` of each entry (the
        previous behaviour of ``client.models()``).
    """

    object: str = "list"
    data: List[ModelInfo] = Field(default_factory=list)

    @property
    def ids(self) -> List[str]:
        """Return only the ``id`` field of each listed model."""
        return [m.id for m in self.data]


# ----------------------------------------------------------------------
# Conversation endpoints
# ----------------------------------------------------------------------
class ConversationResponse(GenerationResponse):
    """
    Response for ``/api/conversation_with_model``.

    ``response`` is the assistant's reply text.
    """

    response: Optional[str] = None


class ExtendedConversationResponse(GenerationResponse):
    """
    Response for ``/api/extended_conversation_with_model``.

    ``response`` is the assistant's reply text.
    """

    response: Optional[str] = None


# ----------------------------------------------------------------------
# Utility endpoints – per‑text (list) outputs
# ----------------------------------------------------------------------
class Polarity3cItem(BaseResponse):
    """Single result entry for ``/api/polarity_3c``."""

    original: str = ""
    polarity: str = ""


class Polarity3cResponse(GenerationResponse):
    """
    Response for ``/api/polarity_3c``.

    ``response`` is a list of :class:`Polarity3cItem`, one per input text.
    """

    response: List[Polarity3cItem] = Field(default_factory=list)


class TranslateItem(BaseResponse):
    """Single result entry for ``/api/translate``."""

    original: str = ""
    translated: str = ""


class TranslateResponse(GenerationResponse):
    """
    Response for ``/api/translate``.

    ``response`` is a list of :class:`TranslateItem`, one per input text.
    """

    response: List[TranslateItem] = Field(default_factory=list)


class SimplifyTextResponse(GenerationResponse):
    """
    Response for ``/api/simplify_text``.

    ``response`` is a list of simplified text strings.
    """

    response: List[str] = Field(default_factory=list)


class TextQuestions(BaseResponse):
    """Single result entry for ``/api/generate_questions``."""

    text: str = ""
    questions: List[str] = Field(default_factory=list)


class GenerateQuestionsResponse(GenerationResponse):
    """
    Response for ``/api/generate_questions``.

    ``response`` is a list of :class:`TextQuestions`, one per input text.
    """

    response: List[TextQuestions] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Utility endpoints – single‑text outputs
# ----------------------------------------------------------------------
class GenerativeAnswerResponse(GenerationResponse):
    """
    Response for ``/api/generative_answer``.

    ``response`` is the generated answer text.
    """

    response: Optional[str] = None


class GenerateLabelResponse(GenerationResponse):
    """
    Response for ``/api/generate_label``.

    ``response`` is the generated category label text.
    """

    response: Optional[str] = None


# ----------------------------------------------------------------------
# Utility endpoints – article outputs
# ----------------------------------------------------------------------
class ArticleText(BaseResponse):
    """
    Nested ``article_text`` payload returned by the article endpoints.
    """

    article_text: Optional[str] = None


class GenerateArticleFromTextResponse(GenerationResponse):
    """
    Response for ``/api/generate_article_from_text``.

    ``response`` is an :class:`ArticleText` object.
    """

    response: ArticleText = Field(default_factory=ArticleText)


class CreateFullArticleFromTextsResponse(GenerationResponse):
    """
    Response for ``/api/create_full_article_from_texts``.

    ``response`` is an :class:`ArticleText` object.
    """

    response: ArticleText = Field(default_factory=ArticleText)


class GenerateArticleFromTextsResponse(GenerationResponse):
    """
    Response for ``/api/generate_article_from_texts``.

    ``response`` is an :class:`ArticleText` object.
    """

    response: ArticleText = Field(default_factory=ArticleText)
