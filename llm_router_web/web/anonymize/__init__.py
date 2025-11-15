# Python
import os
from flask import Flask, redirect, url_for

# Blueprint znajduje się w tym samym pakiecie
from .routes import anonymize_bp


def create_anonymize_app() -> Flask:
    """
    Lekką aplikację Flask, której jedynym zadaniem jest obsługa
    endpointu /anonymize.
    """
    app = Flask(
        __name__,
        # współdzielimy zasoby statyczne z główną aplikacją
        static_folder=os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "static")
        ),
        # szablony znajdują się w web/anonymize/templates
        template_folder=os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "templates")
        ),
    )

    # ---- Konfiguracja (zmienne środowiskowe) ----
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-me-anonymizer")
    # Adres zewnętrznego serwisu anonimizującego
    app.config["LLM_ROUTER_HOST"] = os.getenv(
        "LLM_ROUTER_HOST", "http://localhost:8000"
    )

    # ---- Rejestracja Blueprintu ----
    app.register_blueprint(anonymize_bp)

    @app.route("/", endpoint="index")
    def root():
        # możesz przekierować do formularza lub wyświetlić krótką stronę
        return redirect(url_for("anonymize_web.show_form"))

    # ---- Proste error‑handlery (zwracają JSON) ----
    @app.errorhandler(400)
    def handle_400(error):
        return {"error": error.description or "Bad request"}, 400

    @app.errorhandler(404)
    def handle_404(error):
        return {"error": "Resource not found"}, 404

    @app.errorhandler(500)
    def handle_500(error):
        return {"error": "Internal server error"}, 500

    return app
