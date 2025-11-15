import io
import json

from flask import send_file
from datetime import datetime
from sqlalchemy import func, inspect, text

from .models import db, Config, ConfigVersion, Model


def to_json(config_id: int) -> dict:
    """Serialize a configuration to a JSON‑compatible dict."""
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
    """Create a snapshot of the current config state as a new ConfigVersion."""
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

    cfg = Config.query.get(config_id)
    if cfg:
        cfg.updated_at = datetime.utcnow()
        db.session.add(cfg)

    db.session.commit()


def export_config_to_file(config_id: int):
    """Utility used by the export endpoint – returns a Flask file response."""
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


def _ensure_provider_order_column():
    """
    SQLite does not support automatic migrations. When the code first runs
    against an existing DB the ``order`` column may be missing – this adds it
    if required.
    """
    engine = db.get_engine()
    inspector = inspect(engine)

    # ----------------------------------------------------------------------
    # If the ``provider`` table does not exist yet (first start‑up), simply
    # return – ``db.create_all()`` will create the whole schema later.
    # ----------------------------------------------------------------------
    if not inspector.has_table("provider"):
        return

    current_columns = [c["name"] for c in inspector.get_columns("provider")]
    if "order" not in current_columns:
        with engine.connect() as conn:
            conn.execute(
                text(
                    'ALTER TABLE provider ADD COLUMN "order" INTEGER NOT NULL DEFAULT 0'
                )
            )
        # Refresh SQLAlchemy's metadata so the new column is recognised.
        db.metadata.clear()
        db.metadata.reflect(bind=engine)
