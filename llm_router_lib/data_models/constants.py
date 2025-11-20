# from typing import List, Dict, Any

LANGUAGE_PARAM = "language"
SYSTEM_PROMPT = "system_prompt"
MODEL_NAME_PARAM = "model_name"

MODEL_NAME_PARAMS = [MODEL_NAME_PARAM, "model"]

# POSSIBLE_FIELDS_WITH_TEXTS = {
#     # Text-like
#     "text": str,
#     "text_str": str,
#     "language": str,
#     "user_query": str,
#     "article_type": str,
#     "question_str": str,
#     "user_last_statement": str,
#     # Prompt messages
#     "system_prompt" "": str,
#     "question_prompt": str,
#     # Model name
#     "model_name": str,
#     # Dict like: k and v will be anonymized
#     "messages": List[Dict[str, Any]],
#     "texts": Dict[str, List[str]] | List[str],
#     "historical_messages": List[Dict[str, str]],
# }


CLEAR_PREDEFINED_PARAMS = [
    "response_time",
    "anonymize",
    "anonymize_algorithm",
    "model_name_anonymize",
]
