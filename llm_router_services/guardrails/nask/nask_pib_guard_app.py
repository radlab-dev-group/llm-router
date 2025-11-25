import os
from typing import Any, Dict

from flask import Flask, request, jsonify

from guardrails.constants import SERVICES_API_PREFIX
from guardrails.inference.factory import GuardrailModelFactory

# Import the NASK‑specific configuration
from guardrails.nask.config import NaskModelConfig

# -----------------------------------------------------------------------
# Environment prefix – all configuration keys start with this value
# -----------------------------------------------------------------------
_ENV_PREFIX = "LLM_ROUTER_NASK_PIB_GUARD_"

app = Flask(__name__)

MODEL_PATH = os.getenv(
    f"{_ENV_PREFIX}MODEL_PATH",
    "/mnt/data2/llms/models/community/NASK-PIB/HerBERT-PL-Guard",
)

# Keep only a single constant for the device (CPU by default)
DEFAULT_DEVICE = int(os.getenv(f"{_ENV_PREFIX}DEVICE", "-1"))

# -----------------------------------------------------------------------
# Build the guardrail object via the factory, passing the NASK‑specific config
# -----------------------------------------------------------------------
guardrail = GuardrailModelFactory(
    model_type="text_classification",
    model_path=MODEL_PATH,
    device=DEFAULT_DEVICE,
    config=NaskModelConfig(),  # <-- NASK‑specific thresholds & batch size
)


# -----------------------------------------------------------------------
# Endpoint: POST /api/guardrails/nask_guard
# -----------------------------------------------------------------------
@app.route(f"{SERVICES_API_PREFIX}/nask_guard", methods=["POST"])
def nask_guardrail():
    """
    Accepts a JSON payload, classifies the content and returns the aggregated results.
    """
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON"}), 400

    payload: Dict[str, Any] = request.get_json()
    try:
        results = guardrail.classify_chunks(payload)
        return jsonify({"results": results}), 200
    except Exception as exc:  # pragma: no cover – safety net
        return jsonify({"error": str(exc)}), 500


# -----------------------------------------------------------------------
# Run the Flask server (only when executed directly)
# -----------------------------------------------------------------------
if __name__ == "__main__":
    host = os.getenv(f"{_ENV_PREFIX}FLASK_HOST", "0.0.0.0")
    port = int(os.getenv(f"{_ENV_PREFIX}FLASK_PORT", "5000"))
    app.run(host=host, port=port, debug=False)
