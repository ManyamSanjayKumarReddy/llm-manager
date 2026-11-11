"""Model settings and scheduler timings are validated strictly."""

from typing import Any, cast

import pydantic
import pytest

from llm_manager.core.models_config import ModelSpec
from llm_manager.core.settings import Settings


def spec(**extra: object) -> ModelSpec:
    return ModelSpec.model_validate({"url": "http://a:8000", "gpus": [0], **extra})


def test_a_valid_model_loads() -> None:
    model = spec(gpus=[0, 1], idle_minutes=5, backend_api_key="secret", priority=3)
    assert model.gpus == frozenset({0, 1})
    assert model.idle_seconds == 300
    assert model.backend_key == "secret"
    assert model.priority == 3


def test_priority_defaults_to_zero_and_urls_are_tidied() -> None:
    model = spec(url=" http://a:8000/ ")
    assert model.priority == 0
    assert model.url == "http://a:8000"
    assert model.backend_key is None


@pytest.mark.parametrize(
    "bad",
    [
        {"gpus": []},  # needs a GPU
        {"gpus": [99]},  # no such GPU number
        {"gpus": [-1]},
        {"url": "ftp://a"},  # only http(s)
        {"url": "http://user:pw@a"},  # no credentials in the address
        {"url": "http://169.254.169.254"},  # cloud metadata address
        {"url": "nonsense"},
        {"idle_minutes": 0},
        {"priority": -1},
        {"priority": 101},
        {"backend_api_key": "has space"},
        {"backend_api_key": "line\nbreak"},
        {"backend_api_key": ""},
        {"surprise": 1},  # unknown field
    ],
)
def test_invalid_models_are_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(pydantic.ValidationError):
        spec(**bad)


def test_cookie_name_depends_on_secure() -> None:
    assert (
        Settings(_env_file=None, database_url="x", cookie_secure=True).session_cookie_name
        == "__Host-lm_session"
    )
    assert (
        Settings(_env_file=None, database_url="x", cookie_secure=False).session_cookie_name
        == "lm_session"
    )


def test_allowed_origins_are_split() -> None:
    settings = Settings(
        _env_file=None, database_url="x", allowed_origins="https://a.example, https://b.example"
    )
    assert settings.allowed_origins == ["https://a.example", "https://b.example"]


def test_scheduler_timings_have_defaults_and_can_be_set_in_the_environment() -> None:
    engine = Settings(_env_file=None, database_url="x").engine
    assert (
        engine.queue_timeout_s,
        engine.min_awake_s,
        engine.priority_hold_s,
        engine.sleep_level,
    ) == (120.0, 10.0, 10.0, 1)
    tuned = Settings(_env_file=None, database_url="x", queue_timeout_s=30, min_awake_s=2).engine
    assert (tuned.queue_timeout_s, tuned.min_awake_s) == (30.0, 2.0)


@pytest.mark.parametrize("field", ["queue_timeout_s", "wake_timeout_s", "reaper_interval_s"])
def test_timings_must_be_positive(field: str) -> None:
    with pytest.raises(pydantic.ValidationError):
        Settings(_env_file=None, database_url="x", **cast("dict[str, Any]", {field: 0}))
    with pytest.raises(pydantic.ValidationError):
        Settings(_env_file=None, database_url="x", sleep_level=3)


def test_a_key_does_not_show_up_when_a_model_is_printed() -> None:
    model = spec(backend_api_key="super-secret-key")
    assert "super-secret-key" not in repr(model)
    assert "super-secret-key" not in str(model.model_dump())
    assert "super-secret-key" not in model.model_dump_json()
