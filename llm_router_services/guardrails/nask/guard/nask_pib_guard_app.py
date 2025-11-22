import os
from typing import Any, Dict

from flask import Flask, request, jsonify

# ----------------------------------------------------------------------
from guardrails.constants import SERVICES_API_PREFIX
from guardrails.nask.processor import GuardrailProcessor

# ----------------------------------------------------------------------
# Environment prefix – all configuration keys start with this value
#   * LLM_ROUTER_NASK_PIB_GUARD_FLASK_HOST
#   * LLM_ROUTER_NASK_PIB_GUARD_FLASK_PORT
#   * LLM_ROUTER_MODEL_PATH
# ----------------------------------------------------------------------
_ENV_PREFIX = "LLM_ROUTER_NASK_PIB_GUARD_"

app = Flask(__name__)

MODEL_PATH = os.getenv(
    f"{_ENV_PREFIX}MODEL_PATH",
    "/mnt/data2/llms/models/community/NASK-PIB/HerBERT-PL-Guard",
)

# Keep only a single constant for the device (CPU by default)
DEFAULT_DEVICE = int(os.getenv(f"{_ENV_PREFIX}DEVICE", "-1"))

guardrail_processor = GuardrailProcessor(
    model_path=MODEL_PATH,
    device=DEFAULT_DEVICE,
)


# ----------------------------------------------------------------------
# Endpoint: POST /guardrails/nask_guardrail
# ----------------------------------------------------------------------
@app.route(f"{SERVICES_API_PREFIX}/nask_guard", methods=["POST"])
def nask_guardrail():
    """
    Accepts a JSON payload (as sent by :class:`HttpPluginInterface` via
    ``_request``), classifies the content and returns the aggregated results.
    """
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON"}), 400

    # The request body itself is the payload expected by the processor
    payload: Dict[str, Any] = request.get_json()
    try:
        results = guardrail_processor.classify_chunks(payload)
        return jsonify({"results": results}), 200
    except Exception as exc:  # pragma: no cover – safety net
        return jsonify({"error": str(exc)}), 500


# ----------------------------------------------------------------------
# Run the Flask server (only when executed directly)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    host = os.getenv(f"{_ENV_PREFIX}FLASK_HOST", "0.0.0.0")
    port = int(os.getenv(f"{_ENV_PREFIX}FLASK_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
