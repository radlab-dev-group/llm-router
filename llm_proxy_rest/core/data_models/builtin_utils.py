from typing import Dict, List, Optional

from llm_proxy_rest.core.data_models.builtin_chat import (
    _GenerativeOptionsModel,
    GENAI_REQ_ARGS_BASE,
    GENAI_OPT_ARGS_BASE,
)

#
# class GenerativeQAModel(_GenerativeOptionsModel):
#     question_str: str
#     question_prompt: str
#     texts: Optional[Dict[str, List[str]]] = None
#     system_prompt: Optional[str] = None
#
#


class GenerateQuestionFromTexts(_GenerativeOptionsModel):
    texts: List[str]
    number_of_questions: int = 1


GENERATE_Q_REQ = ["texts"] + GENAI_REQ_ARGS_BASE
GENERATE_Q_OPT = ["number_of_questions"] + GENAI_OPT_ARGS_BASE


class GenerateArticleFromText(_GenerativeOptionsModel):
    text: str


GENERATE_ART_REQ = ["text"] + GENAI_REQ_ARGS_BASE
GENERATE_ART_OPT = GENAI_OPT_ARGS_BASE


#
#
# class CreateArticleFromNewsList(_GenerativeOptionsModel):
#     user_query: str
#     texts: List[str] = None
#     article_type: str | None = None
#
#
# class TranslateTextModel(_GenerativeOptionsModel):
#     texts: List[str] = None
#
#
# class GenerativeSimplification(_GenerativeOptionsModel):
#     texts: List[str]
