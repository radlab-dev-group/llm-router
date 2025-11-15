import os

from flask import Flask, session

from .models import db, Project, User
from .routes import bp as web_bp
from .utils import _ensure_provider_order_column


def create_config_manager_app() -> Flask:
    """Create and configure the Flask application."""
    static_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "static")
    )

    app = Flask(
        __name__,
        static_url_path="/static",
        static_folder=static_path,
        template_folder=os.path.abspath(
            os.path.join(os.path.dirname(__file__), "templates")
        ),
    )

    # ---- Configuration -------------------------------------------------
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-me-local")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL", "sqlite:///configs.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    if os.getenv("FLASK_ENV") == "production":
        app.config["PREFERRED_URL_SCHEME"] = "https"

    # ---- Extensions ----------------------------------------------------
    db.init_app(app)

    # ---- Ensure DB schema (order column) -------------------------------
    with app.app_context():
        _ensure_provider_order_column()
        db.create_all()

    # ---- Register blueprint ---------------------------------------------
    app.register_blueprint(web_bp)

    # ---- Context processor – makes project data available to all templates
    @app.context_processor
    def inject_project_data():
        """
        Provides:
          * Project – the SQLAlchemy model (so templates can query it if needed)
          * user_projects – list of Project objects belonging to the logged‑in user
          * current_project_name – name of the project stored in the session
        """
        user_id = session.get("user_id")
        proj_id = session.get("project_id")
        user_projects = []
        current_name = "—"

        if user_id:
            user_projects = (
                Project.query.filter_by(user_id=user_id).order_by(Project.name).all()
            )
            if proj_id:
                cur = next((p for p in user_projects if p.id == proj_id), None)
                if cur:
                    current_name = cur.name

        return {
            "Project": Project,
            "user_projects": user_projects,
            "current_project_name": current_name,
        }

    # ---- Plain‑name aliases for every blueprint endpoint ----------------
    # After the blueprint is registered Flask knows the full endpoint name
    # (e.g. "web.new_config") and the corresponding URL rule.
    # We iterate over the map and register the same view function under the
    # short name ("new_config") so templates can keep using the original
    # `url_for('new_config')` syntax.
    for rule in list(app.url_map.iter_rules()):
        # Only handle endpoints that belong to the "web" blueprint
        if rule.endpoint.startswith("web."):
            short_name = rule.endpoint.split(".", 1)[1]  # e.g. "new_config"
            # Avoid overwriting an existing plain endpoint (unlikely, but safe)
            if short_name not in app.view_functions:
                app.add_url_rule(
                    rule.rule,
                    endpoint=short_name,
                    view_func=app.view_functions[rule.endpoint],
                    methods=rule.methods,
                )

    # ---- Global error handlers -----------------------------------------
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
