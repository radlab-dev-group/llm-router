"""
Data‑model definitions for built‑in generative chat endpoints.

These pydantic‑style classes describe the request payloads accepted by the
conversation‑related endpoints (e.g. ``ConversationWithModel`` and
``ExtendedConversationWithModel``).  They inherit from the common
``BaseModelOptions`` which supplies generic LLM‑generation options such as
temperature, token limits, and language handling.
"""

from typing import List, Dict, Optional

from llm_router_api.base.constants_base import DEFAULT_EP_LANGUAGE
from llm_router_lib.data_models.base_model import BaseModelOptions
from llm_router_lib.data_models.constants import (
    LANGUAGE_PARAM,
    MODEL_NAME_PARAM,
    SYSTEM_PROMPT,
)


class _GenerativeOptions(BaseModelOptions):
    """
    Core generation‑parameter mix‑in.

    Attributes
    ----------
    temperature : float, default ``0.75``
        Sampling temperature – higher values produce more random output.
    max_new_tokens : int, default ``256``
        Maximum number of tokens to generate in the response.
    top_k : int, default ``50``
        Limit the sampling pool to the top‑k most probable tokens.
    top_p : float, default ``0.99``
        Nucleus sampling – keep the smallest set of tokens with cumulative
        probability >= ``top_p``.
    typical_p : float, default ``1.0``
        Typical‑p sampling parameter.
    repetition_penalty : float, default ``1.2``
        Penalty applied to tokens that have already appeared.
    language : Optional[str], default ``DEFAULT_EP_LANGUAGE``
        Language code (e.g. ``"en"``, ``"pl"``) used by the endpoint; falls back
        to the global default when omitted.
    """

    temperature: float = 0.75
    max_new_tokens: int = 256

    top_k: int = 50
    top_p: float = 0.99
    typical_p: float = 1.0
    repetition_penalty: float = 1.2
    language: Optional[str] = DEFAULT_EP_LANGUAGE


class _GenerativeOptionsModel(_GenerativeOptions):
    """
    Extends ``_GenerativeOptions`` with the mandatory ``model_name`` field.

    The ``model_name`` identifies which downstream LLM should be used for the
    request.
    """

    model_name: str


class GenerativeConversationModel(_GenerativeOptionsModel):
    """
    Payload model for a simple conversation endpoint.

    Parameters
    ----------
    user_last_statement : str
        The latest user utterance that the model should respond to.
    historical_messages : List[Dict[str, str]], default ``[]``
        Optional list of previous dialogue turns.  Each dictionary must contain
        a ``"role"`` key (``"user"`` or ``"assistant"``) and a ``"content"``
        key with the corresponding message text.
    """

    user_last_statement: str
    historical_messages: List[Dict[str, str]] = []


class ExtendedGenerativeConversationModel(GenerativeConversationModel):
    """
    Conversation payload that also accepts an explicit system prompt.

    The ``system_prompt`` is injected as the first message in the conversation,
    allowing callers to steer the model’s behavior (e.g., set a persona or
    provide task‑specific instructions).
    """

    system_prompt: str


GENAI_REQ_ARGS_BASE = [MODEL_NAME_PARAM]
GENAI_OPT_ARGS_BASE = [
    "max_new_tokens",
    "top_k",
    "top_p",
    "temperature",
    "typical_p",
    "repetition_penalty",
    LANGUAGE_PARAM,
]

GENAI_CONV_REQ_ARGS = GENAI_REQ_ARGS_BASE + ["user_last_statement"]
GENAI_CONV_OPT_ARGS = GENAI_OPT_ARGS_BASE + ["historical_messages"]

EXT_GENAI_CONV_REQ_ARGS = GENAI_CONV_REQ_ARGS + [SYSTEM_PROMPT]
EXT_GENAI_CONV_OPT_ARGS = GENAI_CONV_OPT_ARGS
