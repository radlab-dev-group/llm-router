"""
Pydantic‑style request models for the built‑in utility endpoints.

Each class extends ``GenerativeOptionsModel`` (which already supplies the
common generation parameters such as temperature, token limits, and language)
and adds the fields required by a specific endpoint (e.g. a list of source
texts, a single article text, or a question‑and‑context payload).  The
constants that follow enumerate the required and optional argument names
used by the corresponding endpoint classes.
"""

from typing import Dict, List, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from llm_router_lib.data_models.builtin_chat import (
    GenerativeOptionsModel,
    GENAI_REQ_ARGS_BASE,
    GENAI_OPT_ARGS_BASE,
)


# -------------------------------------------------------------------
# Generate question from texts
# -------------------------------------------------------------------
class GenerateQuestionsModel(GenerativeOptionsModel):
    """
    Payload for the "generate‑questions" endpoint.

    Attributes
    ----------
    texts : List[str]
        Source texts from which the model should derive questions.
    number_of_questions : int, default ``1``
        Desired number of questions to generate per input text.
    """

    texts: List[str]
    number_of_questions: int = 1


# Names of parameters that must be present in a request to
# ``GenerateQuestionsModel``
GENERATE_QUESTIONS_REQ = ["texts"] + GENAI_REQ_ARGS_BASE

# Optional parameters that may be supplied
# to fine‑tune generation for question creation.
GENERATE_QUESTIONS_OPT = ["number_of_questions"] + GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Generate article from text (like plg news stream)
# -------------------------------------------------------------------
class GenerateArticleFromTextModel(GenerativeOptionsModel):
    """
    Payload for the "generate‑article" endpoint.

    Attributes
    ----------
    text : str
        The source text (e.g. a news snippet) that the model should expand
        into a full article.
    """

    text: str


# Required fields for ``GenerateArticleFromTextModel``.
GENERATE_ARTICLE_FROM_TEXT_REQ = ["text"] + GENAI_REQ_ARGS_BASE

# Optional generation parameters for article creation.
GENERATE_ARTICLE_FROM_TEXT_OPT = GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Polarity 3c model
# -------------------------------------------------------------------
class Polarity3cModel(GenerativeOptionsModel):
    """
    Payload for the "polarity_3c" endpoint.

    Attributes
    ----------
    texts : List[str]
        Texts for which polarity (ambivalent, positive, negative) should be detected.
    """

    texts: List[str]


# Required arguments for ``Polarity3cModel``.
POLARITY_3C_REQ = ["texts"] + GENAI_REQ_ARGS_BASE

# Optional generation parameters for polarity detection.
POLARITY_3C_OPT = GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Translate text model
# -------------------------------------------------------------------
class TranslateModel(GenerativeOptionsModel):
    """
    Payload for the "translate" endpoint.

    Attributes
    ----------
    texts : List[str]
        Text fragments to be translated by the model.
    """

    texts: List[str]


# Required arguments for ``TranslateModel``.
TRANSLATE_TEXT_REQ = ["texts"] + GENAI_REQ_ARGS_BASE

# Optional generation parameters for translation.
TRANSLATE_TEXT_OPT = GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Simplify text model
# -------------------------------------------------------------------
class SimplifyTextModel(GenerativeOptionsModel):
    """
    Payload for the "simplify‑text" endpoint.

    Attributes
    ----------
    texts : List[str]
        Texts that should be rewritten in a simpler, more accessible style.
    """

    texts: List[str]


# Required arguments for ``SimplifyTextModel``.
SIMPLIFY_TEXT_REQ = ["texts"] + GENAI_REQ_ARGS_BASE

# Optional generation parameters for text simplification.
SIMPLIFY_TEXT_OPT = GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Create article from a mews list (like plg creator)
# -------------------------------------------------------------------
class CreateFullArticleFromTextsModel(GenerativeOptionsModel):
    """
    Payload for the "full‑article" endpoint.

    Attributes
    ----------
    user_query : str
        The query that frames the desired article (used for prompt mapping).
    texts : Optional[List[str]]
        A collection of source texts that will be merged into the final article.
    article_type : Optional[str]
        Optional identifier that can be appended to the system prompt to
        influence the article’s style or format.
    """

    user_query: str
    texts: Optional[List[str]] = None
    article_type: Optional[str] = None


# Required fields for ``CreateFullArticleFromTextsModel``.
CREATE_FULL_ARTICLE_FROM_TEXTS_REQ = ["user_query", "texts"] + GENAI_REQ_ARGS_BASE

# Optional generation parameters for full‑article creation.
CREATE_FULL_ARTICLE_FROM_TEXTS_OPT = ["article_type"] + GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Generate A4‑length article from texts (texts-only endpoint)
# -------------------------------------------------------------------
class GenerateArticleFromTextsModel(GenerativeOptionsModel):
    """
    Payload for the "generate_article_from_texts" endpoint.

    Attributes
    ----------
    texts : List[str]
        Source texts from which the model should produce a short (~A4) article.
    """

    texts: List[str]


# Required/optional args for the texts‑only article generator
GENERATE_ARTICLE_FROM_TEXTS_REQ = ["texts"] + GENAI_REQ_ARGS_BASE
GENERATE_ARTICLE_FROM_TEXTS_OPT = GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Answer based on the context (RAG based)
# -------------------------------------------------------------------
class EnumeratedDocument(BaseModel):
    """One explicitly numbered context fragment; extra metadata is preserved."""

    model_config = ConfigDict(extra="allow")

    n: int = Field(strict=True, gt=0)
    text_str: str
    document_name: str
    text_id: Optional[str | int] = None
    document_id: Optional[str | int] = None
    page_number: Optional[int] = None
    char_start: Optional[int] = Field(default=None, ge=0)
    char_end: Optional[int] = Field(default=None, ge=0)

    @field_validator("text_str")
    @classmethod
    def nonempty_text(cls, value):
        if not value.strip():
            raise ValueError("Numbered fragments must contain text")
        return value

    @model_validator(mode="after")
    def valid_offsets(self):
        if self.char_start is not None and self.char_end is not None:
            if self.char_end < self.char_start:
                raise ValueError("char_end must not precede char_start")
        return self


class QueryHistoryTurn(BaseModel):
    """A complete user/assistant turn used to resolve query references."""

    model_config = ConfigDict(extra="forbid")

    user: str
    assistant: str


class GenerativeAnswerModel(GenerativeOptionsModel):
    """
    Payload for the "generative‑answer" endpoint.

    Attributes
    ----------
    question_str : str
        The user’s question that the model should answer.
    texts : Dict[str, List[str]] | List[str]
        Either a mapping of document name → list of passages or a flat list of
        passages that constitute the knowledge base for retrieval‑augmented
        generation.
    doc_name_in_answer : bool, default ``False``
        When ``True`` and ``texts`` is a dict, the document name is prefixed
        to each passage in the prompt so the model can cite the source.
    question_prompt : Optional[str]
        Optional custom prompt that replaces the default question template.
    system_prompt : Optional[str]
        Optional system‑prompt that can be forced or appended to the request.
    historical_messages : List[QueryHistoryTurn]
        Complete chronological conversation turns, used as context rather
        than instructions or evidence for factual claims.
    """

    question_str: str
    historical_messages: List[QueryHistoryTurn] = Field(default_factory=list)

    # Doc name to texts or list of texts
    texts: Optional[Dict[str, List[str]] | List[str]] = None

    # Explicitly numbered context fragments (RAG citations); see
    # ``EnumeratedDocument``.  Typed as the model so the public contract
    # matches what ``validate_documents`` enforces.
    enumerated_documents: Optional[List[EnumeratedDocument]] = None
    system_prompt_with_enumerated_documents: bool = False

    doc_name_in_answer: bool = False
    question_prompt: Optional[str] = None
    system_prompt: Optional[str] = None

    @field_serializer("enumerated_documents")
    def serialize_documents(self, documents):
        """Emit only the fields the caller supplied.

        A numbered fragment is echoed back in ``citations`` exactly as it was
        given: absent metadata (``page_number``, ``text_id``, …) is omitted
        rather than serialized as ``null``, so callers can correlate a
        citation with their own document record.
        """
        if documents is None:
            return None
        return [document.model_dump(exclude_unset=True) for document in documents]

    @model_validator(mode="after")
    def validate_documents(self):
        if self.enumerated_documents is not None:
            numbers = [document.n for document in self.enumerated_documents]
            if len(numbers) != len(set(numbers)):
                raise ValueError("enumerated_documents must have unique n values")
        return self

    @model_validator(mode="after")
    def validate_context(self):
        if self.system_prompt_with_enumerated_documents:
            if not self.enumerated_documents:
                raise ValueError("Numbered context requires enumerated_documents")
            if self.texts:
                raise ValueError(
                    "Supply either texts or enumerated_documents, not both"
                )
        else:
            if self.enumerated_documents is not None:
                raise ValueError(
                    "enumerated_documents requires system_prompt_with_enumerated_documents=True"
                )
            if self.texts is None:
                raise ValueError("texts is required for legacy context")
        return self


# Required arguments for ``GenerativeAnswerModel``.
GENERATIVE_ANSWER_REQ = ["question_str"] + GENAI_REQ_ARGS_BASE

# Optional generation parameters for context‑aware answering.
GENERATIVE_ANSWER_OPT = [
    "texts",
    "historical_messages",
    "question_prompt",
    "system_prompt",
    "doc_name_in_answer",
    "enumerated_documents",
    "system_prompt_with_enumerated_documents",
] + GENAI_OPT_ARGS_BASE


class RewriteQueryModel(GenerativeOptionsModel):
    """Rewrite the latest statement as a standalone retrieval query."""

    user_last_statement: str = Field(min_length=1)
    historical_messages: List[QueryHistoryTurn] = Field(default_factory=list)

    @field_validator("user_last_statement")
    @classmethod
    def nonempty_statement(cls, value):
        if not value.strip():
            raise ValueError("user_last_statement must not be blank")
        return value


REWRITE_QUERY_REQ = ["user_last_statement"] + GENAI_REQ_ARGS_BASE
REWRITE_QUERY_OPT = ["historical_messages"] + GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Generate a category label/name from a list of texts
# -------------------------------------------------------------------
class GenerateLabelModel(GenerativeOptionsModel):
    """
    Payload for the "generate‑label" endpoint.

    The endpoint receives a list of related texts and asks the model to
    propose a single, concise category name (label) that best captures
    their common essence.

    Attributes
    ----------
    texts : List[str]
        Source texts whose shared essence the model should distil into a
        single category name.
    """

    texts: List[str]


# Required arguments for ``GenerateLabelModel``.
GENERATE_LABEL_REQ = ["texts"] + GENAI_REQ_ARGS_BASE

# Optional generation parameters for label generation.
GENERATE_LABEL_OPT = GENAI_OPT_ARGS_BASE
