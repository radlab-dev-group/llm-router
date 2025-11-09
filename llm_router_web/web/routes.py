import json
import os
from datetime import datetime
from functools import wraps

import requests
from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    flash,
    abort,
    session,
)

from werkzeug.security import generate_password_hash, check_password_hash

from .models import db, Config, ConfigVersion, Model, Provider, ActiveModel, User
from .utils import (
    to_json,
    snapshot_version,
    export_config_to_file,
    VALID_FAMILIES,
)

bp = Blueprint(
    "web",
    __name__,
    template_folder=os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "web/templates")
    ),
)


# ----------------------------------------------------------------------
# Helper decorators
# ----------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def admin_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if session.get("role") != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped_view


# ----------------------------------------------------------------------
# First‑run setup – force creation of an initial admin user
# ----------------------------------------------------------------------
@bp.before_app_request
def ensure_initial_user():
    """
    * If the DB contains no users → force the one‑time setup page.
    * Otherwise require a logged‑in user for every view **except**
      - login
      - setup
      - static assets
    """
    # ----------------------------------------------------------------------
    # 0️⃣  Skip static files (they have no endpoint or endpoint == "static")
    # ----------------------------------------------------------------------
    if request.path.startswith("/static/") or request.endpoint is None:
        return  # let Flask serve the file unchanged

    # ----------------------------------------------------------------------
    # 1️⃣  Normalise endpoint name (remove blueprint prefix)
    # ----------------------------------------------------------------------
    endpoint = request.endpoint or ""
    short_endpoint = endpoint.split(".")[-1]  # "web.login" → "login"

    # ----------------------------------------------------------------------
    # 2️⃣  No users at all → redirect to the *one‑time* setup page
    # ----------------------------------------------------------------------
    if User.query.count() == 0 and short_endpoint != "setup":
        return redirect(url_for("setup"))

    # ----------------------------------------------------------------------
    # 3️⃣  Normal operation – allow only a few public endpoints
    # ----------------------------------------------------------------------
    allowed = {"login", "setup", "static"}
    if short_endpoint not in allowed and "user_id" not in session:
        return redirect(url_for("login"))


# ----------------------------------------------------------------------
# Authentication routes
# ----------------------------------------------------------------------
@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session["user_id"] = user.id
            session["role"] = user.role
            flash("Logged in successfully.", "success")
            return redirect(url_for("index"))
        flash("Invalid credentials.", "error")
        return redirect(url_for("login"))
    return render_template("login.html")


@bp.route("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("login"))


# ----------------------------------------------------------------------
# First‑run admin creation (setup)
# ----------------------------------------------------------------------
@bp.route("/setup", methods=["GET", "POST"])
def setup():
    # This view is reachable only when there are no users in the DB.
    if User.query.count() > 0:
        return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not username or not password:
            flash("Both fields are required.", "error")
            return redirect(url_for("setup"))

        if User.query.filter_by(username=username).first():
            flash("User already exists.", "error")
            return redirect(url_for("setup"))

        admin_user = User(
            username=username,
            password_hash=generate_password_hash(password),
            role="admin",
        )
        db.session.add(admin_user)
        db.session.commit()
        flash("Initial admin user created – you can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("setup.html")


# ----------------------------------------------------------------------
# Admin panel – user management
# ----------------------------------------------------------------------
@bp.route("/admin/users", methods=["GET", "POST"])
@admin_required
def admin_users():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "user")
        if not username or not password:
            flash("Username and password are required.", "error")
        elif User.query.filter_by(username=username).first():
            flash("User already exists.", "error")
        else:
            new_user = User(
                username=username,
                password_hash=generate_password_hash(password),
                role=role,
            )
            db.session.add(new_user)
            db.session.commit()
            flash(f"User {username} added.", "success")
        return redirect(url_for("admin_users"))

    users = User.query.order_by(User.username).all()
    return render_template("admin_users.html", users=users)


# ----------------------------------------------------------------------
# Home & configuration list
# NOTE: we explicitly set endpoint="index" so that url_for('index')
# continues to work even though the view lives inside the "web" blueprint.
# ----------------------------------------------------------------------
@bp.route("/", endpoint="index")
def index():
    configs = Config.query.order_by(Config.updated_at.desc()).all()
    return render_template("index.html", configs=configs)


@bp.route("/configs")
def list_configs():
    configs = Config.query.order_by(Config.updated_at.desc()).all()
    return render_template("configs.html", configs=configs)


# ----------------------------------------------------------------------
# Create / import
# ----------------------------------------------------------------------
@bp.route("/configs/new", methods=["GET", "POST"])
def new_config():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            abort(400, description="Name is required.")
        if Config.query.filter_by(name=name).first():
            abort(400, description="Configuration with this name already exists.")
        cfg = Config(name=name)
        db.session.add(cfg)
        db.session.commit()
        snapshot_version(cfg.id, note="Created empty config")
        return redirect(url_for("web.edit_config", config_id=cfg.id))
    return render_template("new_config.html")


@bp.route("/configs/import", methods=["GET", "POST"])
def import_config():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        raw = request.files.get("file")
        text = request.form.get("json")
        try:
            data = json.load(raw) if raw else json.loads(text or "")
        except Exception:
            flash("Invalid JSON.", "error")
            return redirect(url_for("web.import_config"))

        if not name:
            name = f"import-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        if Config.query.filter_by(name=name).first():
            flash("Name already taken.", "error")
            return redirect(url_for("web.import_config"))

        cfg = Config(name=name)
        db.session.add(cfg)
        db.session.flush()

        # Load models & providers
        for fam in ["google_models", "openai_models", "qwen_models"]:
            for mname, mval in (data.get(fam) or {}).items():
                m = Model(config_id=cfg.id, family=fam, name=mname)
                db.session.add(m)
                for p in mval.get("providers", []):
                    db.session.add(
                        Provider(
                            model=m,
                            provider_id=p.get("id", ""),
                            api_host=p.get("api_host", ""),
                            api_token=p.get("api_token", ""),
                            api_type=p.get("api_type", ""),
                            input_size=int(p.get("input_size", 4096) or 4096),
                            model_path=p.get("model_path", ""),
                            weight=float(p.get("weight", 1.0) or 1.0),
                            enabled=True,
                        )
                    )

        # Active models
        active = data.get("active_models") or {}
        for fam in ["google_models", "openai_models", "qwen_models"]:
            for mname in active.get(fam, []):
                db.session.add(
                    ActiveModel(config_id=cfg.id, family=fam, model_name=mname)
                )

        db.session.commit()
        snapshot_version(cfg.id, note="Import JSON")
        return redirect(url_for("web.edit_config", config_id=cfg.id))
    return render_template("import.html")


# ----------------------------------------------------------------------
# View / export / edit
# ----------------------------------------------------------------------
@bp.route("/configs/<int:config_id>")
def view_config(config_id):
    cfg = Config.query.get_or_404(config_id)
    data = to_json(cfg.id)
    versions = (
        ConfigVersion.query.filter_by(config_id=cfg.id)
        .order_by(ConfigVersion.version.desc())
        .all()
    )
    pretty = {
        "active_models": json.dumps(
            data.get("active_models", {}), ensure_ascii=False, indent=2
        ),
        "google_models": json.dumps(
            data.get("google_models", {}), ensure_ascii=False, indent=2
        ),
        "openai_models": json.dumps(
            data.get("openai_models", {}), ensure_ascii=False, indent=2
        ),
        "qwen_models": json.dumps(
            data.get("qwen_models", {}), ensure_ascii=False, indent=2
        ),
    }
    return render_template(
        "view.html", cfg=cfg, data=data, versions=versions, pretty=pretty
    )


@bp.route("/configs/<int:config_id>/export")
def export_config(config_id):
    return export_config_to_file(config_id)


@bp.route("/configs/<int:config_id>/edit", methods=["GET", "POST"])
def edit_config(config_id):
    cfg = Config.query.get_or_404(config_id)
    if request.method == "POST":
        note = request.form.get("note", "")
        # Update active models
        for fam in ["google_models", "openai_models", "qwen_models"]:
            ActiveModel.query.filter_by(config_id=cfg.id, family=fam).delete()
            for mname in request.form.getlist(f"{fam}[]"):
                db.session.add(
                    ActiveModel(config_id=cfg.id, family=fam, model_name=mname)
                )
        db.session.commit()
        snapshot_version(cfg.id, note=note or "Updated active models")
        return redirect(url_for("web.edit_config", config_id=cfg.id))

    families = {
        fam: Model.query.filter_by(config_id=cfg.id, family=fam).all()
        for fam in ["google_models", "openai_models", "qwen_models"]
    }
    actives = {
        fam: [a.model_name for a in cfg.actives if a.family == fam]
        for fam in ["google_models", "openai_models", "qwen_models"]
    }
    return render_template("edit.html", cfg=cfg, families=families, actives=actives)


# ----------------------------------------------------------------------
# Model & provider management
# ----------------------------------------------------------------------
@bp.route("/configs/<int:config_id>/models/add", methods=["POST"])
def add_model(config_id: int):
    fam = request.form.get("family")
    name = request.form.get("name", "").strip()
    if fam not in VALID_FAMILIES or not name:
        abort(400, description="Invalid data")
    if Model.query.filter_by(config_id=config_id, family=fam, name=name).first():
        abort(400, description="Model already exists")
    m = Model(config_id=config_id, family=fam, name=name)
    db.session.add(m)
    db.session.commit()
    snapshot_version(config_id, note=f"Added model {name}")
    return jsonify({"ok": True, "model_id": m.id})


@bp.post("/models/<int:model_id>/delete")
def delete_model(model_id):
    m = Model.query.get_or_404(model_id)
    cfg_id = m.config_id
    db.session.delete(m)
    db.session.commit()
    snapshot_version(cfg_id, note="Model deleted")
    return jsonify({"ok": True})


@bp.route("/models/<int:model_id>/providers/add", methods=["POST"])
def add_provider(model_id: int):
    m = Model.query.get_or_404(model_id)
    payload = request.get_json(silent=True) or {}
    max_order = (
        db.session.query(func.max(Provider.order)).filter_by(model_id=m.id).scalar()
        or 0
    )
    p = Provider(
        model=m,
        provider_id=payload.get("id", ""),
        api_host=payload.get("api_host", ""),
        api_token=payload.get("api_token", ""),
        api_type=payload.get("api_type", ""),
        input_size=int(payload.get("input_size", 4096) or 4096),
        model_path=payload.get("model_path", ""),
        weight=float(payload.get("weight", 1.0) or 1.0),
        enabled=bool(payload.get("enabled", True)),
        order=max_order + 1,
    )
    if p.api_type not in {"vllm", "openai", "ollama"}:
        abort(400, description="Unsupported api_type")
    db.session.add(p)
    db.session.commit()
    snapshot_version(m.config_id, note=f"Added provider to {m.name}")
    return jsonify({"ok": True, "provider_id": p.id})


@bp.post("/models/<int:model_id>/providers/reorder")
def reorder_providers(model_id):
    m = Model.query.get_or_404(model_id)
    payload = request.json or {}
    ids = payload.get("order", [])
    if not isinstance(ids, list):
        return jsonify({"ok": False, "error": "Invalid payload"}), 400

    for idx, pid in enumerate(ids):
        p = Provider.query.filter_by(id=pid, model_id=model_id).first()
        if p:
            p.order = idx
    db.session.commit()
    snapshot_version(m.config_id, note="Reordered providers")
    return jsonify({"ok": True})


@bp.post("/providers/<int:provider_id>/update")
def update_provider(provider_id):
    p = Provider.query.get_or_404(provider_id)
    payload = request.json or {}
    for field in ["provider_id", "api_host", "api_token", "api_type", "model_path"]:
        if field in payload:
            setattr(p, field, payload[field])
    if "input_size" in payload:
        p.input_size = int(payload["input_size"])
    if "weight" in payload:
        p.weight = float(payload["weight"])
    if "enabled" in payload:
        p.enabled = bool(payload["enabled"])
    db.session.commit()
    snapshot_version(p.model.config_id, note=f"Updated provider {p.provider_id}")
    return jsonify({"ok": True})


@bp.post("/providers/<int:provider_id>/delete")
def delete_provider(provider_id):
    p = Provider.query.get_or_404(provider_id)
    cfg_id = p.model.config_id
    db.session.delete(p)
    db.session.commit()
    snapshot_version(cfg_id, note=f"Deleted provider {p.provider_id}")
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# Configuration activation
# ----------------------------------------------------------------------
@bp.post("/configs/<int:config_id>/activate")
def set_active_config(config_id):
    cfg = Config.query.get_or_404(config_id)
    Config.query.update({Config.is_active: False})
    cfg.is_active = True
    db.session.commit()
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# Version handling
# ----------------------------------------------------------------------
@bp.get("/configs/<int:config_id>/versions")
def list_versions(config_id):
    versions = (
        ConfigVersion.query.filter_by(config_id=config_id)
        .order_by(ConfigVersion.version.desc())
        .all()
    )
    return jsonify(
        [
            {
                "version": v.version,
                "created_at": v.created_at.isoformat(),
                "note": v.note,
            }
            for v in versions
        ]
    )


@bp.post("/configs/<int:config_id>/versions/<int:version>/restore")
def restore_version(config_id, version):
    cfg = Config.query.get_or_404(config_id)
    v = ConfigVersion.query.filter_by(
        config_id=config_id, version=version
    ).first_or_404()
    data = json.loads(v.json_blob)

    # wipe current models & actives
    Model.query.filter_by(config_id=cfg.id).delete()
    ActiveModel.query.filter_by(config_id=cfg.id).delete()
    db.session.flush()

    # load models & providers
    for fam in ["google_models", "openai_models", "qwen_models"]:
        for mname, mval in (data.get(fam) or {}).items():
            m = Model(config_id=cfg.id, family=fam, name=mname)
            db.session.add(m)
            for p in mval.get("providers", []):
                db.session.add(
                    Provider(
                        model=m,
                        provider_id=p.get(1.0) or 1.0,
                        enabled=True,
                    )
                )

    # load active models
    for fam in ["google_models", "openai_models", "qwen_models"]:
        for mname in data.get("active_models", {}).get(fam) or []:
            db.session.add(
                ActiveModel(config_id=cfg.id, family=fam, model_name=mname)
            )

    db.session.commit()
    snapshot_version(cfg.id, note=f"Restored version {version}")
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# Utility endpoint – host check
# ----------------------------------------------------------------------
@bp.post("/check_host")
def check_host():
    data = request.get_json() or {}
    url = data.get("url", "").strip()
    if not url:
        return jsonify({"error": "Missing url"}), 400

    try:
        resp = requests.get(url, timeout=5)
        return jsonify({"status": resp.status_code})
    except Exception as exc:  # pragma: no cover
        return jsonify({"error": str(exc)}), 500
