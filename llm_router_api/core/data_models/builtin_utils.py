from typing import Dict, List, Optional

from llm_router_api.core.data_models.builtin_chat import (
    _GenerativeOptionsModel,
    GENAI_REQ_ARGS_BASE,
    GENAI_OPT_ARGS_BASE,
)


# -------------------------------------------------------------------
# Generate question from texts
# -------------------------------------------------------------------
class GenerateQuestionFromTextsModel(_GenerativeOptionsModel):
    texts: List[str]
    number_of_questions: int = 1


GENERATE_Q_REQ = ["texts"] + GENAI_REQ_ARGS_BASE
GENERATE_Q_OPT = ["number_of_questions"] + GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Generate article from text (like plg news stream)
# -------------------------------------------------------------------
class GenerateArticleFromTextModel(_GenerativeOptionsModel):
    text: str


GENERATE_ART_REQ = ["text"] + GENAI_REQ_ARGS_BASE
GENERATE_ART_OPT = GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Translate text model
# -------------------------------------------------------------------
class TranslateTextModel(_GenerativeOptionsModel):
    texts: List[str]


TRANSLATE_TEXT_REQ = ["texts"] + GENAI_REQ_ARGS_BASE
TRANSLATE_TEXT_OPT = GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Simplify text model
# -------------------------------------------------------------------
class SimplifyTextModel(_GenerativeOptionsModel):
    texts: List[str]


SIMPLIFY_TEXT_REQ = ["texts"] + GENAI_REQ_ARGS_BASE
SIMPLIFY_TEXT_OPT = GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Create article from a mews list (like plg creator)
# -------------------------------------------------------------------
class CreateArticleFromNewsList(_GenerativeOptionsModel):
    user_query: str
    texts: List[str] = None
    article_type: str | None = None


FULL_ARTICLE_REQ = ["user_query", "texts"] + GENAI_REQ_ARGS_BASE
FULL_ARTICLE_OPT = ["article_type"] + GENAI_OPT_ARGS_BASE


# -------------------------------------------------------------------
# Answer based on the context (RAG based)
# -------------------------------------------------------------------
class AnswerBasedOnTheContextModel(_GenerativeOptionsModel):
    question_str: str

    # Doc name to texts or list of texts
    texts: Dict[str, List[str]] | List[str]

    doc_name_in_answer: bool = False
    question_prompt: Optional[str] = None
    system_prompt: Optional[str] = None


CONTEXT_ANSWER_REQ = ["question_str", "texts"] + GENAI_REQ_ARGS_BASE
CONTEXT_ANSWER_OPT = ["question_prompt", "system_prompt"] + GENAI_OPT_ARGS_BASE
