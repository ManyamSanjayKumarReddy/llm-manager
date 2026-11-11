"""Tortoise configuration, shared by the application and by Aerich (migrations)."""

from typing import Any

from pydantic import ValidationError

from llm_manager.core.settings import get_settings

MODEL_MODULES = ["llm_manager.db.models", "aerich.models"]


def build_tortoise_config(database_url: str) -> dict[str, Any]:
    """Return a Tortoise ORM config for ``database_url`` (postgres://user:pw@host:5432/db)."""
    return {
        "connections": {"default": database_url},
        "apps": {"models": {"models": MODEL_MODULES, "default_connection": "default"}},
        "use_tz": True,
        "timezone": "UTC",
    }


def _database_url() -> str:
    """The URL from the environment or ``.env``; empty if unset (e.g. while only linting)."""
    try:
        return get_settings().database_url
    except ValidationError:
        return ""


# Aerich imports this name (see [tool.aerich] in pyproject.toml). The URL comes from the
# environment so credentials never live in the repository.
TORTOISE_ORM = build_tortoise_config(_database_url())
