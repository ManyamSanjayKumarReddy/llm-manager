"""Scheduler settings: edited by admins, saved in the database, applied to the live scheduler."""

import asyncio

import httpx

from llm_manager.core.models_config import EngineConfig
from llm_manager.core.settings import Settings
from llm_manager.db.models import AuditLog, Role, SchedulerSettings
from llm_manager.services.scheduler_settings import stored_engine_config
from tests.conftest import Stack, StackFactory

URL = "/api/settings/scheduler"
VALUES = {
    "queue_timeout_s": 300.0,
    "min_awake_s": 20.0,
    "priority_hold_s": 5.0,
    "preempt_after_s": 45.0,
    "wake_timeout_s": 90.0,
    "sleep_timeout_s": 60.0,
    "reaper_interval_s": 15.0,
    "sleep_level": 1,
}


async def admin(stack: Stack) -> httpx.AsyncClient:
    await stack.create_user()
    return await stack.login()


async def test_shows_the_values_in_force_and_the_defaults(make_stack: StackFactory) -> None:
    client = await admin(await make_stack(queue_timeout_s=33.0))
    body = (await client.get(URL)).json()
    assert body["values"]["queue_timeout_s"] == 33.0
    assert body["defaults"] == EngineConfig().model_dump()
    assert body["defaults"]["preempt_after_s"] is None
    assert body["updated_at"] is None


async def test_saving_applies_at_once_and_is_stored(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    saved = await client.put(URL, json=VALUES)
    assert saved.status_code == 200
    assert saved.json()["values"] == VALUES
    assert saved.json()["updated_by"] == "admin"

    config = stack.container.manager.config
    assert (config.queue_timeout_s, config.min_awake_s, config.preempt_after_s) == (300, 20, 45)
    assert (await client.get(URL)).json()["values"] == VALUES

    # After a restart the saved values win over the environment.
    restarted = await stored_engine_config(Settings(_env_file=None, database_url="x"))
    assert restarted.queue_timeout_s == 300.0
    assert restarted.preempt_after_s == 45.0
    entry = await AuditLog.filter(action="settings.scheduler").first()
    assert entry is not None
    assert "queue_timeout_s=300.0" in (entry.detail or "")


async def test_without_a_saved_row_the_environment_values_apply(db: None) -> None:
    settings = Settings(_env_file=None, database_url="x", queue_timeout_s=77)
    assert (await SchedulerSettings.all().count()) == 0
    assert (await stored_engine_config(settings)).queue_timeout_s == 77


async def test_preemption_can_be_switched_off_again(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await client.put(URL, json=VALUES)
    await client.put(URL, json={**VALUES, "preempt_after_s": None})
    assert stack.container.manager.config.preempt_after_s is None
    assert (await client.get(URL)).json()["values"]["preempt_after_s"] is None


async def test_a_shorter_queue_timeout_applies_to_requests_already_waiting(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack(queue_timeout_s=60.0)
    client = await admin(stack)
    token = await stack.api_key()
    slow = asyncio.create_task(stack.chat(token, "a", work_s=2.0))
    await asyncio.sleep(0.1)
    waiting = asyncio.create_task(stack.chat(token, "b"))  # b needs a's GPU
    await asyncio.sleep(0.2)
    values = {**VALUES, "queue_timeout_s": 0.5, "preempt_after_s": None}
    assert (await client.put(URL, json=values)).status_code == 200
    assert (await waiting).status_code == 503
    assert (await slow).status_code == 200


async def test_bad_values_are_rejected(make_stack: StackFactory) -> None:
    client = await admin(await make_stack())
    for change in (
        {"preempt_after_s": 300.0},  # not smaller than the queue timeout
        {"queue_timeout_s": 0},
        {"queue_timeout_s": -1},
        {"min_awake_s": -1},
        {"sleep_level": 3},
        {"wake_timeout_s": 10**9},
        {"extra": 1},
    ):
        response = await client.put(URL, json={**VALUES, **change})
        assert response.status_code == 422, change
    missing = {k: v for k, v in VALUES.items() if k != "min_awake_s"}
    assert (await client.put(URL, json=missing)).status_code == 422


async def test_only_admins_can_see_or_change_them(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user("viewer1", Role.VIEWER, "a-long-passphrase")
    viewer = await stack.login("viewer1", "a-long-passphrase")
    assert (await viewer.get(URL)).status_code == 403
    assert (await viewer.put(URL, json=VALUES)).status_code == 403
    assert (await stack.anonymous().get(URL)).status_code == 401
