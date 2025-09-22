from typing import Dict, List, Optional

from llm_proxy_rest.endpoints.data_models.genai import _GenerativeOptionsModel


class GenerativeQAModel(_GenerativeOptionsModel):
    question_str: str
    question_prompt: str
    texts: Optional[Dict[str, List[str]]] = None
    system_prompt: Optional[str] = None


class GenerativeConversationModel(_GenerativeOptionsModel):
    user_last_statement: str
    historical_messages: List[Dict[str, str]]


class ExtendedGenerativeConversationModel(GenerativeConversationModel):
    system_prompt: str


class GenerativeQuestionGeneratorModel(_GenerativeOptionsModel):
    number_of_questions: int = 1
    texts: List[str] = None


class GenerativeArticleFromText(_GenerativeOptionsModel):
    text: str


class CreateArticleFromNewsList(_GenerativeOptionsModel):
    user_query: str
    texts: List[str] = None
    article_type: str | None = None


class TranslateTextModel(_GenerativeOptionsModel):
    texts: List[str] = None


class GenerativeSimplification(_GenerativeOptionsModel):
    texts: List[str]
