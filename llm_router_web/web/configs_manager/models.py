from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


# --------------------------------------------------------------
# Project – groups configs per user
# --------------------------------------------------------------
class Project(db.Model):
    __tablename__ = "project"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )
    # A project can be marked as the user's default
    is_default = db.Column(db.Boolean, default=False, nullable=False)

    # free‑text description for the project
    description = db.Column(db.String(500), nullable=False, default="")

    # One‑to‑many relationship: a project owns many configs
    configs = db.relationship(
        "Config", backref="project", cascade="all, delete-orphan"
    )

    def __repr__(self):
        return f"<Project {self.name} (user_id={self.user_id})>"


class Config(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False,
        index=True,
    )
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("project.id"),
        nullable=False,
        index=True,
    )

    # Free‑text description for the configuration
    description = db.Column(db.String(500), nullable=False, default="")

    # ------------------------------------------------------------------
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
        "Provider",
        backref="model",
        cascade="all, delete-orphan",
        order_by="Provider.order",
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
    order = db.Column(db.Integer, nullable=False, default=0)


class ActiveModel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    config_id = db.Column(db.Integer, db.ForeignKey("config.id"), nullable=False)
    family = db.Column(db.String(40), nullable=False)
    model_name = db.Column(db.String(200), nullable=False)


class User(db.Model):
    """Simple user model used for authentication and role management."""

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(
        db.String(20),
        nullable=False,
        default="user",  # possible values: "admin", "user"
    )
    is_active = db.Column(
        db.Boolean,
        nullable=False,
        default=True,  # active by default
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    projects = db.relationship(
        "Project",
        backref="owner",
        cascade="all, delete-orphan",
    )

    configs = db.relationship(
        "Config",
        backref="owner",  # access via cfg.owner
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<User {self.username} ({self.role})>"
