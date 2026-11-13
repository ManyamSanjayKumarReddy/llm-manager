"""Database tables.

Secrets are never stored: passwords are argon2id hashes, and session tokens and API keys
are stored as SHA-256 digests (the plain token is shown to its owner once).
"""

from enum import StrEnum
from typing import ClassVar

from tortoise import fields, timezone
from tortoise.models import Model


class Role(StrEnum):
    """What a dashboard user may do."""

    ADMIN = "admin"  # everything, including users and API keys
    VIEWER = "viewer"  # read-only dashboard


class User(Model):
    """A person who may log in to the dashboard. Created by an admin; no self-registration."""

    id = fields.UUIDField(primary_key=True)
    username = fields.CharField(max_length=64, unique=True)
    password_hash = fields.TextField()
    role = fields.CharEnumField(Role, max_length=16)
    is_active = fields.BooleanField(default=True)
    failed_attempts = fields.IntField(default=0)
    locked_until = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    last_login_at = fields.DatetimeField(null=True)
    password_changed_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        """Table options."""

        table = "users"


class Session(Model):
    """A browser login session."""

    id = fields.UUIDField(primary_key=True)
    user: fields.ForeignKeyRelation[User] = fields.ForeignKeyField(
        "models.User", related_name="sessions", on_delete=fields.CASCADE
    )
    token_hash = fields.CharField(max_length=64, unique=True)
    csrf_token = fields.CharField(max_length=64)
    created_at = fields.DatetimeField(auto_now_add=True)
    last_seen_at = fields.DatetimeField(auto_now_add=True)
    expires_at = fields.DatetimeField(db_index=True)
    ip = fields.CharField(max_length=64, null=True)
    user_agent = fields.CharField(max_length=300, null=True)

    class Meta:
        """Table options."""

        table = "sessions"


class ApiKey(Model):
    """A credential for programs calling ``/v1/*``."""

    id = fields.UUIDField(primary_key=True)
    label = fields.CharField(max_length=100)
    prefix = fields.CharField(max_length=16)  # first characters, to recognise a key
    key_hash = fields.CharField(max_length=64, unique=True)
    created_by: fields.ForeignKeyNullableRelation[User] = fields.ForeignKeyField(
        "models.User", related_name="api_keys", null=True, on_delete=fields.SET_NULL
    )
    created_at = fields.DatetimeField(auto_now_add=True)
    last_used_at = fields.DatetimeField(null=True)
    revoked_at = fields.DatetimeField(null=True)
    allowed_models = fields.JSONField[list[str]](null=True)  # None = all models
    rpm_limit = fields.IntField(null=True)  # None = unlimited

    class Meta:
        """Table options."""

        table = "api_keys"


class RequestLog(Model):
    """One proxied request (no prompts or responses are stored)."""

    id = fields.BigIntField(primary_key=True)
    ts = fields.DatetimeField(auto_now_add=True, db_index=True)
    model = fields.CharField(max_length=100)
    api_key: fields.ForeignKeyNullableRelation[ApiKey] = fields.ForeignKeyField(
        "models.ApiKey", related_name="requests", null=True, on_delete=fields.SET_NULL
    )
    status = fields.IntField()
    duration_ms = fields.IntField()
    queue_wait_ms = fields.IntField()

    class Meta:
        """Table options."""

        table = "request_log"
        indexes: ClassVar = [("model", "ts")]


class Event(Model):
    """A wake/sleep/failure event of the router."""

    id = fields.BigIntField(primary_key=True)
    ts = fields.DatetimeField(default=timezone.now, db_index=True)
    model = fields.CharField(max_length=100, null=True)
    kind = fields.CharField(max_length=40)
    detail = fields.TextField(default="")

    class Meta:
        """Table options."""

        table = "events"


class AuditLog(Model):
    """Who did what: logins, user changes, API key changes."""

    id = fields.BigIntField(primary_key=True)
    ts = fields.DatetimeField(auto_now_add=True, db_index=True)
    actor = fields.CharField(max_length=100)
    action = fields.CharField(max_length=60)
    target = fields.CharField(max_length=200, null=True)
    ip = fields.CharField(max_length=64, null=True)
    detail = fields.TextField(null=True)

    class Meta:
        """Table options."""

        table = "audit_log"


class Server(Model):
    """A machine with GPUs that runs vLLM containers. Models are placed on one."""

    id = fields.UUIDField(primary_key=True)
    name = fields.CharField(max_length=64, unique=True)
    gpu_count = fields.IntField()
    gpu_type = fields.CharField(max_length=100, null=True)  # free text, e.g. "2x RTX 4060 Ti 16 GB"
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        """Table options."""

        table = "servers"


class ManagedModel(Model):
    """A vLLM container the router manages. Registered from the dashboard."""

    id = fields.UUIDField(primary_key=True)
    name = fields.CharField(max_length=64, unique=True)
    server: fields.ForeignKeyRelation[Server] = fields.ForeignKeyField(
        "models.Server", related_name="models", on_delete=fields.RESTRICT
    )
    url = fields.CharField(max_length=300)
    served_name = fields.CharField(max_length=200, null=True)
    gpus = fields.JSONField[list[int]]()
    idle_minutes = fields.FloatField(default=10.0)
    priority = fields.IntField(default=0)
    # The container's own API key. The router must send it as-is, so it cannot be hashed; the
    # API never returns it (see ModelOut.has_api_key).
    backend_api_key: str | None = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        """Table options."""

        table = "managed_models"
