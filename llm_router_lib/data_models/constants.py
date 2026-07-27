"""
String constants used by data‑model classes to identify field names in API
requests.  All values must match the backend's expected parameter keys exactly.
"""

LANGUAGE_PARAM = "language"
SYSTEM_PROMPT = "system_prompt"
MODEL_NAME_PARAM = "model_name"

MODEL_NAME_PARAMS = [MODEL_NAME_PARAM, "model"]

CLEAR_PREDEFINED_PARAMS = [
    "response_time",
    "mask_payload",
    "masker_pipeline",
]
