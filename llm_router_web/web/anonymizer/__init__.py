import os
from flask import Flask, redirect, url_for

# Blueprint is located in the same package
from .routes import anonymize_bp


def create_anonymize_app() -> Flask:
    """
    A lightweight Flask application whose sole purpose is to handle
    the /anonymize endpoint.
    """
    app = Flask(
        __name__,
        # Share static resources with the main application
        static_folder=os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "static")
        ),
        # Templates are located in web/anonymize/templates
        template_folder=os.path.abspath(
            os.path.join(os.path.dirname(__file__), "templates")
        ),
    )

    # ---- Configuration (environment variables) ----
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-me-anonymizer")
    # Address of the external anonymizing service
    app.config["LLM_ROUTER_HOST"] = os.getenv(
        "LLM_ROUTER_HOST", "http://localhost:8000"
    )

    # ---- Blueprint registration ----
    app.register_blueprint(anonymize_bp)

    @app.route("/", endpoint="index")
    def root():
        # You can redirect to a form or display a short page
        return redirect(url_for("anonymize_web.show_form"))

    # ---- Simple error handlers (return JSON) ----
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
