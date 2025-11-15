# -*- coding: utf-8 -*-

"""
Flask blueprint for the text anonymization web interface.

Provides two endpoints:
* GET  /anonymize/ – renders the input form.
* POST /anonymize/ – sends the supplied text to the external anonymization
  service and displays the result.
"""

import requests

from flask import Blueprint, current_app, request, render_template


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
    """
    Render the form (anonymize.html).

    The template receives:
    * api_host – base URL of the LLM router service.
    * result   – initially ``None`` (no result to display yet).
    """
    return render_template(
        "anonymize.html",
        api_host=current_app.config["LLM_ROUTER_HOST"],
        result=None,
    )


@anonymize_bp.route("/", methods=["POST"])
def process_text():
    """
    Send the submitted text to the external anonymization API and render the result.
    """
    raw_text = request.form.get("text", "")
    if not raw_text:
        return "⚠️ No text provided.", 400

    # New: get selected algorithm (default to fast)
    algorithm = request.form.get("algorithm", "fast")

    # Map algorithm to the corresponding endpoint path
    endpoint_map = {
        "fast": "/api/fast_text_mask",
        "genai": "/api/anonymize_text_genai",
        "priv": "/api/anonymize_text_priv_masker",
    }

    if algorithm == "genai":
        if not GENAI_MODEL_ANON:
            return render_template(
                "anonymize_result_partial.html",
                api_host=current_app.config["LLM_ROUTER_HOST"],
                result={"error": "genai model is not set"},
            )
    elif algorithm == "priv":
        return render_template(
            "anonymize_result_partial.html",
            api_host=current_app.config["LLM_ROUTER_HOST"],
            result={"error": "priv_masker is not available yet"},
        )
    elif algorithm == "fast":
        pass
    else:
        return render_template(
            "anonymize_result_partial.html",
            api_host=current_app.config["LLM_ROUTER_HOST"],
            result={
                "error": f"Not supported method {algorithm}.\nSupported: [fast, genai, priv]"
            },
        )

    endpoint = endpoint_map[algorithm]

    # Build the external service URL (ensure no duplicate slash)
    external_url = f"{current_app.config['LLM_ROUTER_HOST'].rstrip('/')}{endpoint}"

    try:
        resp = requests.post(
            external_url,
            json={"text": raw_text, "model_name": "gpt-oss:120b"},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        return f"❌ Connection error with the anonymization service: {exc}", 502

    # The response may be JSON or plain text
    try:
        data = resp.json()
        result = data.get("text", resp.text)
    except ValueError:
        result = resp.text

    # Render the same template, now with the result filled in
    return render_template(
        "anonymize_result_partial.html",
        api_host=current_app.config["LLM_ROUTER_HOST"],
        result=result,
    )
