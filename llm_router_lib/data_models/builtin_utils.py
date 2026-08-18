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

from llm_router_lib.data_models.builtin_chat import (
    GenerativeOptionsModel,
    GENAI_REQ_ARGS_BASE,
    GENAI_OPT_ARGS_BASE,
)


# -------------------------------------------------------------------
# Generate question from texts
# -------------------------------------------------------------------
class GenerateQuestionFromTextsModel(GenerativeOptionsModel):
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
# ``GenerateQuestionFromTextsModel``
GENERATE_Q_REQ = ["texts"] + GENAI_REQ_ARGS_BASE

# Optional parameters that may be supplied
# to fine‑tune generation for question creation.
GENERATE_Q_OPT = ["number_of_questions"] + GENAI_OPT_ARGS_BASE


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
GENERATE_ART_REQ = ["text"] + GENAI_REQ_ARGS_BASE

# Optional generation parameters for article creation.
GENERATE_ART_OPT = GENAI_OPT_ARGS_BASE


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
class TranslateTextModel(GenerativeOptionsModel):
    """
    Payload for the "translate" endpoint.

    Attributes
    ----------
    texts : List[str]
        Text fragments to be translated by the model.
    """

    texts: List[str]


# Required arguments for ``TranslateTextModel``.
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
class CreateArticleFromNewsListModel(GenerativeOptionsModel):
    """
    Payload for the "full‑article" endpoint.

    Attributes
    ----------
    user_query : str
        The query that frames the desired article (used for prompt mapping).
    texts : List[str] | None
        A collection of source texts that will be merged into the final article.
    article_type : str | None
        Optional identifier that can be appended to the system prompt to
        influence the article’s style or format.
    """

    user_query: str
    texts: Optional[List[str]] = None
    article_type: Optional[str] = None


# Required fields for ``CreateArticleFromNewsListModel``.
FULL_ARTICLE_REQ = ["user_query", "texts"] + GENAI_REQ_ARGS_BASE

# Optional generation parameters for full‑article creation.
FULL_ARTICLE_OPT = ["article_type"] + GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Answer based on the context (RAG based)
# -------------------------------------------------------------------
class AnswerBasedOnTheContextModel(GenerativeOptionsModel):
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
    """

    question_str: str

    # Doc name to texts or list of texts
    texts: Dict[str, List[str]] | List[str]

    doc_name_in_answer: bool = False
    question_prompt: Optional[str] = None
    system_prompt: Optional[str] = None


# Required arguments for ``AnswerBasedOnTheContextModel``.
CONTEXT_ANSWER_REQ = ["question_str", "texts"] + GENAI_REQ_ARGS_BASE

# Optional generation parameters for context‑aware answering.
CONTEXT_ANSWER_OPT = ["question_prompt", "system_prompt"] + GENAI_OPT_ARGS_BASE
