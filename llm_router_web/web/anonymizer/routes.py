# -*- coding: utf-8 -*-

"""
Flask blueprint for the text anonymization web interface.

Provides endpoints for:
* anonymization form
* anonymization processing
* chat UI
* model catalogue (proxy to the LLM‑Router `/models` endpoint)
"""

import requests
from flask import Blueprint, current_app, request, render_template, jsonify

from .constants import GENAI_MODEL_ANON

# Blueprint configuration
anonymize_bp = Blueprint(
    "anonymize_web",
    __name__,
    url_prefix="/anonymize",  # http://HOST:PORT/anonymize
    template_folder="../templates",  # templates in web/anonymize/templates
)


@anonymize_bp.route("/", methods=["GET"])
def show_form():
    """Render the anonymization form."""
    return render_template(
        "anonymize.html",
        api_host=current_app.config["LLM_ROUTER_HOST"],
        result=None,
    )


@anonymize_bp.route("/", methods=["POST"])
def process_text():
    """Send text to the external anonymization service and render the result."""
    raw_text = request.form.get("text", "")
    if not raw_text:
        return "⚠️ No text provided.", 400

    algorithm = request.form.get("algorithm", "fast")
    endpoint_map = {
        "fast": "/api/fast_text_mask",
        "genai": "/api/anonymize_text_genai",
        "priv": "/api/anonymize_text_priv_masker",
    }

    if algorithm == "genai" and not GENAI_MODEL_ANON:
        return render_template(
            "anonymize_result_partial.html",
            api_host=current_app.config["LLM_ROUTER_HOST"],
            result={"error": "genai model is not set"},
        )
    if algorithm == "priv":
        return render_template(
            "anonymize_result_partial.html",
            api_host=current_app.config["LLM_ROUTER_HOST"],
            result={"error": "priv_masker is not available yet"},
        )
    if algorithm not in endpoint_map:
        return render_template(
            "anonymize_result_partial.html",
            api_host=current_app.config["LLM_ROUTER_HOST"],
            result={
                "error": f"Not supported method {algorithm}.\nSupported: [fast, genai, priv]"
            },
        )

    endpoint = endpoint_map[algorithm]
    external_url = f"{current_app.config['LLM_ROUTER_HOST'].rstrip('/')}{endpoint}"

    try:
        resp = requests.post(
            external_url,
            json={"text": raw_text, "model_name": "gpt-oss:120b"},
            timeout=60,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        return f"❌ Connection error with the anonymization service: {exc}", 502

    try:
        data = resp.json()
        result = data.get("text", resp.text)
    except ValueError:
        result = resp.text

    return render_template(
        "anonymize_result_partial.html",
        api_host=current_app.config["LLM_ROUTER_HOST"],
        result=result,
    )


# ----------------------------------------------------------------------
# Chat UI
# ----------------------------------------------------------------------
@anonymize_bp.route("/chat", methods=["GET"])
def show_chat():
    """Render the dedicated chat page."""
    return render_template(
        "chat.html",
        api_host=current_app.config["LLM_ROUTER_HOST"],
    )


@anonymize_bp.route("/chat/message", methods=["POST"])
def chat_message():
    """Forward a chat message to the LLM‑Router and render the reply."""
    user_msg = request.form.get("message", "")
    if not user_msg:
        return "⚠️ No message provided.", 400

    algorithm = request.form.get("algorithm", "fast")
    model_name = request.form.get("model_name", "").strip()

    # If GenAI was chosen but no model supplied, inform the user.
    if algorithm == "genai" and not model_name:
        return render_template(
            "chat_partial.html",
            chat="❌ GenAI selected but no model provided. Please select a model.",
        )

    print("algorithm=", algorithm)
    print("algorithm=", algorithm)
    print("algorithm=", algorithm)

    payload = {
        "stream": False,
        "anonymize": algorithm != "no_anno",
        "model": model_name or "google/gemma-3-12b-it",
        "messages": [{"role": "user", "content": user_msg}],
    }

    external_url = (
        f"{current_app.config['LLM_ROUTER_HOST'].rstrip('/')}" "/v1/chat/completions"
    )

    try:
        resp = requests.post(
            external_url,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        return f"❌ Chat service error: {exc}", 502

    try:
        data = resp.json()
        chat_reply = (
            data.get("choices", [{}])[0].get("message", {}).get("content", "")
        )
        if not chat_reply:
            chat_reply = data.get("message", {}).get("content", "")
    except (ValueError, AttributeError):
        chat_reply = ""

    return render_template(
        "chat_partial.html",
        chat=chat_reply,
    )


# ----------------------------------------------------------------------
# Model catalogue – proxy to the router’s `/models` endpoint
# ----------------------------------------------------------------------
@anonymize_bp.route("/models", methods=["GET"])
def models():
    """
    Retrieve the list of available models from the external LLM‑Router.
    The frontend calls this endpoint (e.g. via `fetch`) to fill the model dropdown.
    """
    external_url = f"{current_app.config['LLM_ROUTER_HOST'].rstrip('/')}" "/models"
    try:
        resp = requests.get(external_url, timeout=10)
        resp.raise_for_status()
    except requests.RequestException as exc:
        # Return an empty list with a 500 status so the client can handle it.
        current_app.logger.error(f"Failed to fetch models: {exc}")
        return jsonify({"models": []}), 500

    try:
        data = resp.json()
    except ValueError:
        # Non‑JSON response – treat as empty list.
        current_app.logger.error("Models endpoint returned non‑JSON.")
        return jsonify({"models": []}), 500

    # The router may return either {"data": [...]} or {"models": [...]}
    models = data.get("models") or data.get("data") or []
    return jsonify({"models": models})
