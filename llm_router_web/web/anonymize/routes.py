# Python
from flask import Blueprint, current_app, request, render_template
import requests

anonymize_bp = Blueprint(
    "anonymize_web",
    __name__,
    url_prefix="/anonymize",  # → http://HOST:PORT/anonymize
    template_folder="../templates",  # szablony w web/anonymize/templates
)


@anonymize_bp.route("/", methods=["GET"])
def show_form():
    """Renderuje formularz (anonymize.html)."""
    return render_template(
        "anonymize.html",
        api_host=current_app.config["LLM_ROUTER_HOST"],
        result=None,
    )


@anonymize_bp.route("/", methods=["POST"])
def process_text():
    """Wysyła tekst do zewnętrznego API i zwraca wynik."""
    raw_text = request.form.get("text", "")
    if not raw_text:
        return "⚠️ Nie podano tekstu.", 400

    external_url = (
        f"{current_app.config['LLM_ROUTER_HOST'].rstrip('/')}/api/anonymize_text"
    )

    try:
        resp = requests.post(
            external_url,
            json={"text": raw_text},
            timeout=10,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        return f"❌ Błąd połączenia z usługą anonimizacji: {exc}", 502

    # Odpowiedź może być JSON lub czysty tekst
    try:
        data = resp.json()
        result = data.get("anonymized_text", resp.text)
    except ValueError:
        result = resp.text

    # Renderujemy ten sam szablon, ale z wypełnionym wynikiem
    return render_template(
        "anonymize_result_partial.html",
        api_host=current_app.config["LLM_ROUTER_HOST"],
        result=result,
    )
