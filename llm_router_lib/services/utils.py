"""
Utility service wrappers for built‑in endpoints.

The file defines thin subclasses of :class:`BaseConversationServiceInterface`
that bind a concrete HTTP endpoint and the Pydantic model used for payload
validation.  These services can be instantiated with a ``HttpRequester`` and
a logger and then called via the ``.call()`` method provided by the base
class.
"""

from llm_router_lib.data_models.builtin_utils import (
    GenerateQuestionsModel,
    Polarity3cModel,
    TranslateModel,
    GenerativeAnswerModel,
    GenerateArticleFromTextModel,
    CreateFullArticleFromTextsModel,
    GenerateArticleFromTextsModel,
    SimplifyTextModel,
    GenerateLabelModel,
)

from llm_router_lib.services.service_interface import (
    BaseConversationServiceInterface,
)


class Polarity3cService(BaseConversationServiceInterface):
    """
    Service for the ``/api/polarity_3c`` endpoint.

    The service posts a payload validated by :class:`Polarity3cModel` to the
    polarity classification endpoint and returns the parsed JSON response.
    All request handling (including error conversion to :class:`LLMRouterError`)
    is inherited from :class:`BaseConversationServiceInterface`.

    Attributes
    ----------
    endpoint : str
        Relative URL of the polarity endpoint (``"/api/polarity_3c"``).
    model_cls : type
        The Pydantic model class used to validate request data
        (:class:`Polarity3cModel`).
    """

    endpoint = "/api/polarity_3c"
    model_cls = Polarity3cModel


class TranslateService(BaseConversationServiceInterface):
    """
    Service for the ``/api/translate`` endpoint.

    The service posts a payload validated by :class:`TranslateModel` to the
    translation endpoint and returns the parsed JSON response.  All request
    handling (including error conversion to :class:`LLMRouterError`) is
    inherited from :class:`BaseConversationServiceInterface`.

    Attributes
    ----------
    endpoint : str
        Relative URL of the translation endpoint (``"/api/translate"``).
    model_cls : type
        The Pydantic model class used to validate request data
        (:class:`TranslateModel`).
    """

    endpoint = "/api/translate"
    model_cls = TranslateModel


class SimplifyTextService(BaseConversationServiceInterface):
    """
    Service for the ``/api/simplify_text`` endpoint.

    The service posts a payload validated by :class:`SimplifyTextModel` to the
    text‑simplification endpoint and returns the parsed JSON response.  All
    request handling (including error conversion to :class:`LLMRouterError`) is
    inherited from :class:`BaseConversationServiceInterface`.

    Attributes
    ----------
    endpoint : str
        Relative URL of the simplification endpoint (``"/api/simplify_text"``).
    model_cls : type
        The Pydantic model class used to validate request data
        (:class:`SimplifyTextModel`).
    """

    endpoint = "/api/simplify_text"
    model_cls = SimplifyTextModel


class GenerativeAnswerService(BaseConversationServiceInterface):
    endpoint = "/api/generative_answer"
    model_cls = GenerativeAnswerModel


class GenerateArticleFromTextService(BaseConversationServiceInterface):
    endpoint = "/api/generate_article_from_text"
    model_cls = GenerateArticleFromTextModel


class CreateFullArticleFromTextsService(BaseConversationServiceInterface):
    """
    Service for the ``/api/create_full_article_from_texts`` endpoint.

    Posts a payload validated by :class:`CreateFullArticleFromTextsModel` and
    returns the parsed JSON response.
    """

    endpoint = "/api/create_full_article_from_texts"
    model_cls = CreateFullArticleFromTextsModel


class GenerateArticleFromTextsService(BaseConversationServiceInterface):
    """
    Service for the ``/api/generate_article_from_texts`` endpoint.

    Posts a payload validated by :class:`GenerateArticleFromTextsModel` and
    returns the parsed JSON response.
    """

    endpoint = "/api/generate_article_from_texts"
    model_cls = GenerateArticleFromTextsModel


class GenerateQuestionsService(BaseConversationServiceInterface):
    """
    Service for the ``/api/generate_questions`` endpoint.

    Posts a payload validated by :class:`GenerateQuestionsModel` and
    returns the parsed JSON response.
    """

    endpoint = "/api/generate_questions"
    model_cls = GenerateQuestionsModel


class GenerateLabelService(BaseConversationServiceInterface):
    """
    Service for the ``/api/generate_label`` endpoint.

    Posts a payload validated by :class:`GenerateLabelModel` and returns the
    parsed JSON response containing a single category name (label) for the
    supplied texts.
    """

    endpoint = "/api/generate_label"
    model_cls = GenerateLabelModel
