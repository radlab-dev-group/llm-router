from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    jsonify,
    send_file,
    flash,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from datetime import datetime
import json
import io

app = Flask(__name__, static_url_path="/static", static_folder="static")
app.config["SECRET_KEY"] = "change-me-local"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///configs.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    models = db.relationship("Model", backref="config", cascade="all, delete-orphan")
    actives = db.relationship(
        "ActiveModel", backref="config", cascade="all, delete-orphan"
    )
    versions = db.relationship(
        "ConfigVersion", backref="config", cascade="all, delete-orphan"
    )


class ConfigVersion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(db.Integer, db.ForeignKey("config.id"), nullable=False)
    version = db.Column(db.Integer, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    note = db.Column(db.String(200), default="")
    json_blob = db.Column(db.Text, nullable=False)


class Model(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(db.Integer, db.ForeignKey("config.id"), nullable=False)
    family = db.Column(
        db.String(40), nullable=False
    )  # google_models | openai_models | qwen_models
    name = db.Column(db.String(200), nullable=False)
    providers = db.relationship(
        "Provider", backref="model", cascade="all, delete-orphan"
    )


class Provider(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.Integer, db.ForeignKey("model.id"), nullable=False)
    provider_id = db.Column(db.String(200), nullable=False)
    api_host = db.Column(db.String(400), nullable=False)
    api_token = db.Column(db.String(400), default="")
    api_type = db.Column(db.String(40), nullable=False)  # vllm | openai | ollama
    input_size = db.Column(db.Integer, default=4096, nullable=False)
    model_path = db.Column(db.String(200), default="")
    weight = db.Column(db.Float, default=1.0, nullable=False)
    enabled = db.Column(db.Boolean, default=True, nullable=False)


class ActiveModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(db.Integer, db.ForeignKey("config.id"), nullable=False)
    family = db.Column(db.String(40), nullable=False)
    model_name = db.Column(db.String(200), nullable=False)


def to_json(config_id: int) -> dict:
    cfg = Config.query.get_or_404(config_id)
    out = {
        "google_models": {},
        "openai_models": {},
        "qwen_models": {},
        "active_models": {
            "google_models": [],
            "openai_models": [],
            "qwen_models": [],
        },
    }
    families = ["google_models", "openai_models", "qwen_models"]
    for fam in families:
        for m in Model.query.filter_by(config_id=cfg.id, family=fam).all():
            providers = []
            for p in m.providers:
                if p.enabled:
                    providers.append(
                        {
                            "id": p.provider_id,
                            "api_host": p.api_host,
                            "api_token": p.api_token,
                            "api_type": p.api_type,
                            "input_size": p.input_size,
                            "model_path": p.model_path,
                            **(
                                {"weight": p.weight}
                                if p.api_type == "vllm" or p.weight != 1.0
                                else {}
                            ),
                        }
                    )
            out[fam][m.name] = {"providers": providers}
    for fam in families:
        out["active_models"][fam] = [
            a.model_name for a in cfg.actives if a.family == fam
        ]
    return out


def snapshot_version(config_id: int, note: str = ""):
    payload = to_json(config_id)
    last = (
        db.session.query(func.max(ConfigVersion.version))
        .filter_by(config_id=config_id)
        .scalar()
        or 0
    )
    v = ConfigVersion(
        config_id=config_id,
        version=last + 1,
        note=note,
        json_blob=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    db.session.add(v)
    db.session.commit()


@app.route("/")
def index():
    configs = Config.query.order_by(Config.updated_at.desc()).all()
    return render_template("index.html", configs=configs)


@app.route("/configs/new", methods=["GET", "POST"])
def new_config():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Nazwa jest wymagana.", "error")
            return redirect(url_for("new_config"))
        if Config.query.filter_by(name=name).first():
            flash("Konfig o takiej nazwie już istnieje.", "error")
            return redirect(url_for("new_config"))
        cfg = Config(name=name)
        db.session.add(cfg)
        db.session.commit()
        snapshot_version(cfg.id, note="Utworzono pusty konfig")
        return redirect(url_for("edit_config", config_id=cfg.id))
    return render_template("new_config.html")


@app.route("/configs/import", methods=["GET", "POST"])
def import_config():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        raw = request.files.get("file")
        text = request.form.get("json")
        data = None
        try:
            data = json.load(raw) if raw else json.loads(text or "")
        except Exception:
            flash("Nieprawidłowy JSON.", "error")
            return redirect(url_for("import_config"))
        if not name:
            name = f"import-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
        if Config.query.filter_by(name=name).first():
            flash("Nazwa zajęta.", "error")
            return redirect(url_for("import_config"))
        cfg = Config(name=name)
        db.session.add(cfg)
        db.session.flush()
        # load models
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
        # actives
        active = data.get("active_models") or {}
        for fam in ["google_models", "openai_models", "qwen_models"]:
            for mname in active.get(fam, []):
                db.session.add(
                    ActiveModel(config_id=cfg.id, family=fam, model_name=mname)
                )
        db.session.commit()
        snapshot_version(cfg.id, note="Import JSON")
        return redirect(url_for("edit_config", config_id=cfg.id))
    return render_template("import.html")


@app.route("/configs")
def list_configs():
    configs = Config.query.order_by(Config.updated_at.desc()).all()
    return render_template("configs.html", configs=configs)


@app.route("/configs/<int:config_id>")
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


@app.route("/configs/<int:config_id>/export")
def export_config(config_id):
    payload = to_json(config_id)
    buf = io.BytesIO(
        json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    )
    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/json",
        as_attachment=True,
        download_name="models-config.json",
    )


@app.route("/configs/<int:config_id>/edit", methods=["GET", "POST"])
def edit_config(config_id):
    cfg = Config.query.get_or_404(config_id)
    if request.method == "POST":
        note = request.form.get("note", "")
        # Active models update
        for fam in ["google_models", "openai_models", "qwen_models"]:
            ActiveModel.query.filter_by(config_id=cfg.id, family=fam).delete()
            for mname in request.form.getlist(f"{fam}[]"):
                db.session.add(
                    ActiveModel(config_id=cfg.id, family=fam, model_name=mname)
                )
        db.session.commit()
        snapshot_version(cfg.id, note=note or "Aktualizacja aktywnych modeli")
        return redirect(url_for("edit_config", config_id=cfg.id))
    families = {
        fam: Model.query.filter_by(config_id=cfg.id, family=fam).all()
        for fam in ["google_models", "openai_models", "qwen_models"]
    }
    actives = {
        fam: [a.model_name for a in cfg.actives if a.family == fam]
        for fam in ["google_models", "openai_models", "qwen_models"]
    }
    return render_template("edit.html", cfg=cfg, families=families, actives=actives)


@app.post("/configs/<int:config_id>/models/add")
def add_model(config_id):
    fam = request.form.get("family")
    name = request.form.get("name", "").strip()
    if fam not in {"google_models", "openai_models", "qwen_models"} or not name:
        return jsonify({"ok": False, "error": "Błędne dane"}), 400
    exists = Model.query.filter_by(
        config_id=config_id, family=fam, name=name
    ).first()
    if exists:
        return jsonify({"ok": False, "error": "Model już istnieje"}), 400
    m = Model(config_id=config_id, family=fam, name=name)
    db.session.add(m)
    db.session.commit()
    snapshot_version(config_id, note=f"Dodano model {name}")
    return jsonify({"ok": True, "model_id": m.id})


@app.post("/models/<int:model_id>/delete")
def delete_model(model_id):
    m = Model.query.get_or_404(model_id)
    cfg_id = m.config_id
    db.session.delete(m)
    db.session.commit()
    snapshot_version(cfg_id, note="Usunięto model")
    return jsonify({"ok": True})


@app.post("/models/<int:model_id>/providers/add")
def add_provider(model_id):
    m = Model.query.get_or_404(model_id)
    payload = request.json or {}
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
    )
    if p.api_type not in {"vllm", "openai", "ollama"}:
        return jsonify({"ok": False, "error": "Nieobsługiwany api_type"}), 400
    db.session.add(p)
    db.session.commit()
    snapshot_version(m.config_id, note=f"Dodano providera do {m.name}")
    return jsonify({"ok": True, "provider_id": p.id})


@app.post("/providers/<int:provider_id>/update")
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
    snapshot_version(
        p.model.config_id, note=f"Aktualizacja providera {p.provider_id}"
    )
    return jsonify({"ok": True})


@app.post("/configs/<int:config_id>/activate")
def set_active_config(config_id):
    cfg = Config.query.get_or_404(config_id)
    Config.query.update({Config.is_active: False})
    cfg.is_active = True
    db.session.commit()
    return jsonify({"ok": True})


@app.get("/configs/<int:config_id>/versions")
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


@app.post("/configs/<int:config_id>/versions/<int:version>/restore")
def restore_version(config_id, version):
    cfg = Config.query.get_or_404(config_id)
    v = ConfigVersion.query.filter_by(
        config_id=config_id, version=version
    ).first_or_404()
    data = json.loads(v.json_blob)
    # wipe
    Model.query.filter_by(config_id=cfg.id).delete()
    ActiveModel.query.filter_by(config_id=cfg.id).delete()
    db.session.flush()
    # load
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
    for fam in ["google_models", "openai_models", "qwen_models"]:
        for mname in data.get("active_models", {}).get(fam) or []:
            db.session.add(
                ActiveModel(config_id=cfg.id, family=fam, model_name=mname)
            )
    db.session.commit()
    snapshot_version(cfg.id, note=f"Przywrócono v{version}")
    return jsonify({"ok": True})


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=8081, debug=True)
