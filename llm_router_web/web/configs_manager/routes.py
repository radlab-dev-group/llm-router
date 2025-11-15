import os
import json
import requests

from functools import wraps
from sqlalchemy import func
from datetime import datetime

from werkzeug.security import generate_password_hash, check_password_hash

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

from .models import (
    db,
    Config,
    ConfigVersion,
    Model,
    Provider,
    ActiveModel,
    User,
    Project,
)
from .utils import (
    to_json,
    snapshot_version,
    export_config_to_file,
)
from .constants import VALID_FAMILIES

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


def _current_user_id():
    return session.get("user_id")


# ----------------------------------------------------------------------
# Utility: require authentication for actions that create configs
# ----------------------------------------------------------------------
def _require_user():
    """Abort with 403 if no user is logged in."""
    if not _current_user_id():
        abort(403, description="User must be logged in to perform this action.")
    return _current_user_id()


def _create_default_project_for_user(user: User):
    """Utility – called after a new User row is persisted."""
    default_proj = Project(name="default_project", user_id=user.id, is_default=True)
    db.session.add(default_proj)
    db.session.commit()
    # store in session if the newly created user is the one logging in now
    if session.get("user_id") == user.id:
        session["project_id"] = default_proj.id


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
    # If a user is already authenticated, send them to the main page
    if session.get("user_id"):
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        # ---- verify credentials first ----
        if user and check_password_hash(user.password_hash, password):
            # ---- then check if the account is active ----
            if not user.is_active:
                flash("Your account has been blocked.", "error")
                return redirect(url_for("login"))
            # store user details in session for later use in templates
            session["user_id"] = user.id
            session["username"] = user.username
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
        # If a user already exists, prevent re‑access to the setup page.
        # Logged‑in users are sent to the main index, otherwise to the login page.
        if session.get("user_id"):
            return redirect(url_for("index"))
        else:
            return redirect(url_for("login"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if password != password_confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("setup"))

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
        _create_default_project_for_user(admin_user)
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
            _create_default_project_for_user(new_user)
            flash(f"User {username} added.", "success")
        return redirect(url_for("admin_users"))

    users = User.query.order_by(User.username).all()
    return render_template("admin_users.html", users=users)


# ------ Admin: edit user role -------------------------------------------------
@bp.post("/admin/users/<int:user_id>/edit")
@admin_required
def edit_user(user_id):
    if user_id == session.get("user_id"):
        flash("You cannot edit your own account.", "error")
        return redirect(url_for("admin_users"))

    user = User.query.get_or_404(user_id)

    # ----- password change -----
    new_password = request.form.get("new_password")
    confirm_password = request.form.get("confirm_password")
    if new_password:
        # verify confirmation
        if not confirm_password:
            flash("Please repeat the new password.", "error")
            return redirect(url_for("admin_users"))
        if new_password != confirm_password:
            flash("New passwords do not match.", "error")
            return redirect(url_for("admin_users"))
        # securely update the stored password hash
        user.password_hash = generate_password_hash(new_password)
        flash(f"Password for {user.username} updated.", "success")

    # ----- role change -----
    role = request.form.get("role")
    if role:
        if role not in {"admin", "user"}:
            flash(f"Invalid role {role}", "error")
            # if role is invalid and no password change, stop processing
            if not new_password:
                return redirect(url_for("admin_users"))
        else:
            user.role = role
            flash(f"Role for {user.username} updated to {role}.", "success")

    # Commit changes if either password or role was modified
    if new_password or role:
        db.session.commit()

    return redirect(url_for("admin_users"))


# ------ Admin: block / unblock user -------------------------------------------
@bp.post("/admin/users/<int:user_id>/toggle_block")
@admin_required
def toggle_block_user(user_id):
    if user_id == session.get("user_id"):
        flash("You cannot block/unblock yourself.", "error")
        return redirect(url_for("admin_users"))

    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    status = "unblocked" if user.is_active else "blocked"
    flash(f"User {user.username} has been {status}.", "success")
    return redirect(url_for("admin_users"))


# ----------------------------------------------------------------------
# Home & configuration list
# NOTE: we explicitly set endpoint="index" so that url_for('index')
# continues to work even though the view lives inside the "web" blueprint.
# ----------------------------------------------------------------------
@bp.route("/", endpoint="index")
def index():
    user_id = _current_user_id()
    proj_id = _current_project_id()
    configs = (
        Config.query.filter_by(user_id=user_id, project_id=proj_id)
        .order_by(Config.updated_at.desc())
        .all()
    )
    return render_template("index.html", configs=configs)


@bp.route("/change_password", methods=["GET", "POST"])
@login_required
def change_password():
    """Allow the logged‑in user to change their own password."""
    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        confirm_pw = request.form.get("confirm_password", "")

        user = User.query.get_or_404(session["user_id"])

        # Verify current password
        if not check_password_hash(user.password_hash, current_pw):
            flash("Current password is incorrect.", "error")
            return redirect(url_for("change_password"))

        # Verify new passwords match
        if new_pw != confirm_pw:
            flash("New passwords do not match.", "error")
            return redirect(url_for("change_password"))

        # Update password hash
        user.password_hash = generate_password_hash(new_pw)
        db.session.commit()
        flash("Password updated successfully.", "success")
        return redirect(url_for("index"))

    # GET request – render the password change form
    return render_template("change_password.html")


# ----------------------------------------------------------------------
# Helper: retrieve the currently selected project (fallback to default)
# ----------------------------------------------------------------------
def _current_project_id():
    """Return the project ID stored in session or the user's default project."""
    proj_id = session.get("project_id")
    if proj_id:
        return proj_id
    # fallback: look for a default project belonging to the user
    user_id = _current_user_id()
    default_proj = Project.query.filter_by(user_id=user_id, is_default=True).first()
    if default_proj:
        session["project_id"] = default_proj.id
        return default_proj.id
    # if no project exists (should not happen), create one on‑the‑fly
    new_proj = Project(name="default_project", user_id=user_id, is_default=True)
    db.session.add(new_proj)
    db.session.commit()
    session["project_id"] = new_proj.id
    return new_proj.id


# ----------------------------------------------------------------------
# Project selection endpoint (used by the dropdown in the top‑bar)
# ----------------------------------------------------------------------
@bp.post("/projects/select/<int:project_id>")
@login_required
def select_project(project_id):
    """Switch the active project for the current session."""
    user_id = _current_user_id()
    proj = Project.query.filter_by(id=project_id, user_id=user_id).first_or_404()
    session["project_id"] = proj.id
    flash(f"Project “{proj.name}” selected.", "success")
    # Redirect to the list of configs instead of the previous referrer or index
    return redirect(url_for("list_configs"))


# ----------------------------------------------------------------------
# Project management UI (list / create / rename)
# ----------------------------------------------------------------------
@bp.route("/projects", methods=["GET", "POST"])
@login_required
def manage_projects():
    user_id = _current_user_id()
    if request.method == "POST":
        # Create a new project – name supplied via form field ``name``
        name = request.form.get("name", "").strip()
        # NEW: read optional description
        description = request.form.get("description", "").strip()
        if not name:
            flash("Project name is required.", "error")
        else:
            # Ensure uniqueness per user
            if Project.query.filter_by(user_id=user_id, name=name).first():
                flash("You already have a project with that name.", "error")
            else:
                new_proj = Project(
                    name=name,
                    description=description,  # <-- store description
                    user_id=user_id,
                    is_default=False,
                )
                db.session.add(new_proj)
                db.session.commit()
                flash(f"Project “{name}” created.", "success")
        return redirect(url_for("manage_projects"))

    projects = Project.query.filter_by(user_id=user_id).order_by(Project.name).all()
    return render_template("projects.html", projects=projects)


@bp.post("/projects/<int:project_id>/rename")
@login_required
def rename_project(project_id):
    user_id = _current_user_id()
    proj = Project.query.filter_by(id=project_id, user_id=user_id).first_or_404()
    new_name = request.form.get("new_name", "").strip()
    if not new_name:
        flash("New name cannot be empty.", "error")
    else:
        # check for duplicate
        if Project.query.filter_by(user_id=user_id, name=new_name).first():
            flash("Another project already uses this name.", "error")
        else:
            proj.name = new_name
            db.session.commit()
            flash("Project renamed.", "success")
    return redirect(url_for("manage_projects"))


@bp.post("/projects/<int:project_id>/delete")
@login_required
def delete_project(project_id):
    user_id = _current_user_id()
    proj = Project.query.filter_by(id=project_id, user_id=user_id).first_or_404()
    if proj.is_default:
        flash("The default project cannot be deleted.", "error")
        return redirect(url_for("manage_projects"))
    if proj.configs:
        flash("Cannot delete a project that contains configs.", "error")
        return redirect(url_for("manage_projects"))
    db.session.delete(proj)
    db.session.commit()
    # if the deleted project was the active one, clear session entry
    if session.get("project_id") == project_id:
        session.pop("project_id")
    flash("Project deleted.", "success")
    return redirect(url_for("manage_projects"))


# ----------------------------------------------------------------------
# Configs Create / import
# ----------------------------------------------------------------------
@bp.route("/configs")
def list_configs():
    user_id = _current_user_id()
    proj_id = _current_project_id()
    configs = (
        Config.query.filter_by(user_id=user_id, project_id=proj_id)
        .order_by(Config.updated_at.desc())
        .all()
    )
    return render_template("configs.html", configs=configs)


@bp.route("/configs/new", methods=["GET", "POST"])
def new_config():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        # NEW: optional description for the config
        description = request.form.get("description", "").strip()
        if not name:
            abort(400, description="Name is required.")
        proj_id = _current_project_id()
        if Config.query.filter_by(name=name, project_id=proj_id).first():
            abort(
                400,
                description="Configuration with this name already exists in the project.",
            )
        cfg = Config(
            name=name,
            description=description,
            user_id=_current_user_id(),
            project_id=proj_id,
        )
        db.session.add(cfg)
        db.session.commit()
        snapshot_version(cfg.id, note="Created empty config")
        return redirect(url_for("web.edit_config", config_id=cfg.id))
    return render_template("new_config.html")


@bp.route("/configs/import", methods=["GET", "POST"])
def import_config():
    """
    Import a configuration from a JSON file or raw JSON text.

    The form now also accepts an optional ``description`` (Notatka/Opis) which
    is stored on the newly created ``Config`` object.
    """
    # Ensure the user is authenticated before touching the DB
    user_id = _require_user()

    if request.method == "POST":
        # ---- 1️⃣  Basic fields -------------------------------------------------
        name = request.form.get("name", "").strip()
        # NEW: optional description for the imported config
        description = request.form.get("description", "").strip()

        raw = request.files.get("file")
        text = request.form.get("json")

        # ---- 2️⃣  Parse JSON ---------------------------------------------------
        try:
            data = json.load(raw) if raw else json.loads(text or "")
        except Exception:
            flash("Invalid JSON.", "error")
            return redirect(url_for("web.import_config"))

        # ---- 3️⃣  Derive a name if none was supplied -------------------------
        if not name:
            name = f"import-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"

        # ---- 4️⃣  Validate uniqueness -----------------------------------------
        if Config.query.filter_by(name=name, user_id=user_id).first():
            flash("Name already taken.", "error")
            return redirect(url_for("web.import_config"))

        # ---- 5️⃣  Determine the target project --------------------------------
        proj_id = _current_project_id()

        # ---- 6️⃣  Create the Config row (now with description) ---------------
        cfg = Config(
            name=name,
            description=description,  # <-- store description
            user_id=user_id,
            project_id=proj_id,
        )
        db.session.add(cfg)
        db.session.flush()  # obtain cfg.id before adding models/providers

        # ---- 7️⃣  Load models & providers (unchanged logic) -------------------
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

        # ---- 8️⃣  Active models (unchanged) ----------------------------------
        active = data.get("active_models") or {}
        for fam in ["google_models", "openai_models", "qwen_models"]:
            for mname in active.get(fam, []):
                db.session.add(
                    ActiveModel(config_id=cfg.id, family=fam, model_name=mname)
                )

        # ---- 9️⃣  Commit everything & snapshot version -----------------------
        db.session.commit()
        snapshot_version(cfg.id, note="Import JSON")

        # ---- 🔟  Redirect to the edit page for further tweaks ----------------
        return redirect(url_for("web.edit_config", config_id=cfg.id))

    # ---- GET request – render the import form ---------------------------------
    return render_template("import.html")


# ----------------------------------------------------------------------
# View / export / edit
# ----------------------------------------------------------------------
def _get_user_config(config_id):
    """Fetch a config belonging to the current user or abort 404."""
    return Config.query.filter_by(
        id=config_id, user_id=_current_user_id()
    ).first_or_404()


@bp.route("/configs/<int:config_id>")
def view_config(config_id):
    cfg = _get_user_config(config_id)
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
    cfg = _get_user_config(config_id)
    return export_config_to_file(cfg.id)


@bp.route("/configs/<int:config_id>/edit", methods=["GET", "POST"])
def edit_config(config_id):
    cfg = _get_user_config(config_id)
    if request.method == "POST":
        new_name = request.form.get("new_name")
        # NEW: handle description update
        new_description = request.form.get("description")
        if new_name is not None:
            new_name = new_name.strip()
            if new_name and new_name != cfg.name:
                if Config.query.filter_by(
                    name=new_name, user_id=_current_user_id()
                ).first():
                    flash("Configuration name already taken.", "error")
                else:
                    cfg.name = new_name
                    flash("Configuration renamed.", "success")
                    db.session.commit()
            # If only renaming, skip further processing
            return redirect(url_for("web.edit_config", config_id=cfg.id))

        # Update description (if the field is present)
        if new_description is not None:
            cfg.description = new_description.strip()
            db.session.commit()
            flash("Configuration description updated.", "success")

        note = request.form.get("note", "")
        # Update active models (unchanged)
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
    return render_template(
        "edit.html",
        cfg=cfg,
        families=families,
        actives=actives,
    )


# ----------------------------------------------------------------------
# Model & provider management
# ----------------------------------------------------------------------
@bp.route("/configs/<int:config_id>/models/add", methods=["POST"])
def add_model(config_id: int):
    cfg = _get_user_config(config_id)
    fam = request.form.get("family")
    name = request.form.get("name", "").strip()
    if fam not in VALID_FAMILIES or not name:
        abort(400, description="Invalid data")
    if Model.query.filter_by(config_id=cfg.id, family=fam, name=name).first():
        abort(400, description="Model already exists")
    m = Model(config_id=cfg.id, family=fam, name=name)
    db.session.add(m)
    db.session.commit()
    snapshot_version(cfg.id, note=f"Added model {name}")
    return jsonify({"ok": True, "model_id": m.id})


@bp.post("/models/<int:model_id>/delete")
def delete_model(model_id):
    m = Model.query.get_or_404(model_id)
    # ensure the model belongs to the current user
    if m.config.owner.id != _current_user_id():
        abort(403)
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
    cfg = _get_user_config(config_id)
    Config.query.filter_by(user_id=_current_user_id()).update(
        {Config.is_active: False}
    )
    cfg.is_active = True
    db.session.commit()
    return jsonify({"ok": True})


# ----------------------------------------------------------------------
# Configuration deletion
# ----------------------------------------------------------------------
@bp.post("/configs/<int:config_id>/delete")
def delete_config(config_id):
    """Delete a configuration owned by the current user."""
    cfg = _get_user_config(config_id)  # aborts 404 if not owned
    db.session.delete(cfg)
    db.session.commit()
    flash(f"Configuration '{cfg.name}' has been deleted.", "success")
    # --------------------------------------------------------------
    # Determine where to send the user after deletion:
    #   • If the request came from the configs list page, stay there.
    #   • Otherwise (e.g., from the index page) go back to index.
    # --------------------------------------------------------------
    # `request.referrer` contains the full URL of the page that submitted the form.
    # We compare it with the URL generated for the configs list view.
    ref = request.referrer or ""
    configs_url = url_for("list_configs", _external=True)
    if ref.startswith(configs_url):
        return redirect(url_for("list_configs"))
    else:
        return redirect(url_for("index"))


# ----------------------------------------------------------------------
# Version handling
# ----------------------------------------------------------------------
@bp.get("/configs/<int:config_id>/versions")
def list_versions(config_id):
    cfg = _get_user_config(config_id)
    versions = (
        ConfigVersion.query.filter_by(config_id=cfg.id)
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
    cfg = _get_user_config(config_id)
    v = ConfigVersion.query.filter_by(
        config_id=config_id, version=version
    ).first_or_404()
    data = json.loads(v.json_blob)

    # --------------------------------------------------------------
    # 1️⃣  Remove *all* current data – providers, models and actives
    # --------------------------------------------------------------
    # Bulk delete of providers (must be done first, because a bulk
    # Model.delete() would not cascade to providers)
    Provider.query.filter(Provider.model.has(config_id=cfg.id)).delete(
        synchronize_session=False
    )

    # Delete models belonging to this config
    Model.query.filter_by(config_id=cfg.id).delete(synchronize_session=False)

    # Delete active‑model entries
    ActiveModel.query.filter_by(config_id=cfg.id).delete(synchronize_session=False)

    # Commit the deletions so the DB is clean before we re‑populate it
    db.session.commit()

    # --------------------------------------------------------------
    # 2️⃣  Re‑create models & their providers from the snapshot
    # --------------------------------------------------------------
    for fam in ["google_models", "openai_models", "qwen_models"]:
        for mname, mval in (data.get(fam) or {}).items():
            m = Model(config_id=cfg.id, family=fam, name=mname)
            db.session.add(m)
            # ---- recreate providers with correct fields ----
            for idx, p in enumerate(mval.get("providers", [])):
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
                        enabled=bool(p.get("enabled", True)),
                        order=idx,
                    )
                )

    # --------------------------------------------------------------
    # 3️⃣  Re‑create active‑model entries
    # --------------------------------------------------------------
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
