"""Registering, editing, sleeping and removing models from the dashboard."""

import asyncio
import logging

import httpx
import pytest

from llm_manager.db.models import AuditLog, ManagedModel, Role
from llm_manager.services.models import ModelStore
from tests.conftest import PORTS, Stack, StackFactory, model_state

PASSWORD = "a-long-passphrase"
NEW = {
    "name": "model-d",
    "server": "this-server",
    "url": f"http://127.0.0.1:{PORTS['d']}",
    "served_name": "org/d",
    "gpus": [2],
}


def is_asleep(stack: Stack, name: str) -> bool:
    """Whether the fake container really is asleep (read fresh each time)."""
    return stack.fakes[name].sleeping


async def admin(stack: Stack) -> httpx.AsyncClient:
    await stack.create_user()
    return await stack.login()


async def test_registered_models_are_listed_and_there_is_no_config_file_to_edit(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack()
    client = await admin(stack)
    listed = (await client.get("/api/models")).json()
    assert [m["name"] for m in listed["items"]] == ["a", "b", "c"]
    assert listed["total"] == 3
    assert set(await ModelStore.specs()) == {"a", "b", "c"}


async def test_a_fresh_installation_starts_with_no_models(make_stack: StackFactory) -> None:
    stack = await make_stack(models=())
    client = await admin(stack)
    assert (await client.get("/api/models")).json()["total"] == 0
    assert (await client.get("/api/status")).json()["models"] == {}
    token = await stack.api_key()
    assert (await stack.chat(token, "a")).status_code == 404  # nothing registered yet
    created = await client.post("/api/models", json=NEW)  # the first model, from the dashboard
    assert created.status_code == 201
    assert list((await client.get("/api/status")).json()["models"]) == ["model-d"]


async def test_only_admins_manage_models(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user("viewer1", Role.VIEWER, PASSWORD)
    viewer = await stack.login("viewer1", PASSWORD)
    assert (await viewer.get("/api/models")).status_code == 403
    assert (await viewer.post("/api/models", json=NEW)).status_code == 403
    assert (await viewer.post("/api/models/check", json={"url": NEW["url"]})).status_code == 403
    assert (await viewer.patch("/api/models/a", json={"priority": 3})).status_code == 403
    assert (await viewer.delete("/api/models/a")).status_code == 403
    assert (await stack.anonymous().get("/api/models")).status_code == 401


async def test_changes_need_the_csrf_token(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    client.headers.pop("X-CSRF-Token")
    assert (await client.post("/api/models", json=NEW)).status_code == 403
    assert (await client.delete("/api/models/a")).status_code == 403


async def test_register_a_running_container(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    assert not is_asleep(stack, "d")  # it was started by hand, so it is awake

    created = await client.post("/api/models", json=NEW | {"priority": 4, "idle_minutes": 5})
    assert created.status_code == 201, created.text
    body = created.json()
    assert (body["name"], body["gpus"], body["priority"], body["idle_minutes"]) == (
        "model-d",
        [2],
        4,
        5,
    )
    assert is_asleep(stack, "d")  # adopted: put to sleep so the GPU is free
    assert model_state(stack, "model-d") == "asleep"
    assert [m["name"] for m in (await client.get("/api/models")).json()["items"]] == [
        "a",
        "b",
        "c",
        "model-d",
    ]

    # it is immediately usable by programs, and wakes on demand
    token = await stack.api_key()
    models = (
        await stack.anonymous().get("/v1/models", headers={"Authorization": f"Bearer {token}"})
    ).json()
    assert "model-d" in [m["id"] for m in models["data"]]
    assert (await stack.chat(token, "model-d")).status_code == 200
    assert stack.fakes["d"].served == 1
    assert stack.fakes["d"].last_model == "org/d"
    assert await AuditLog.filter(action="model.register", target="model-d").exists()
    assert stack.ledger.violations == []


async def test_registration_survives_a_restart(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await client.post("/api/models", json=NEW)
    specs = await ModelStore.specs()
    assert set(specs) == {"a", "b", "c", "model-d"}
    assert specs["model-d"].gpus == frozenset({2})


async def test_unreachable_container_registers_as_down(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    # the container is not running: connections are refused
    stack.dispatch.down.add(PORTS["d"])
    created = await client.post("/api/models", json=NEW)
    assert created.status_code == 201
    assert created.json()["state"] == "down"


async def test_bad_registrations_are_rejected(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    cases = {
        "duplicate name": NEW | {"name": "a"},
        "name is another model's served name": NEW | {"name": "org/b"},
        "served name taken": NEW | {"served_name": "org/a"},
        "bad name": NEW | {"name": "Has Spaces"},
        "empty name": NEW | {"name": ""},
        "ftp url": NEW | {"url": "ftp://x"},
        "url with password": NEW | {"url": "http://u:p@x:1"},
        "metadata address": NEW | {"url": "http://169.254.169.254"},
        "no gpus": NEW | {"gpus": []},
        "gpu out of range": NEW | {"gpus": [99]},
        "negative priority": NEW | {"priority": -1},
        "huge priority": NEW | {"priority": 101},
        "zero idle": NEW | {"idle_minutes": 0},
        "key with a space": NEW | {"backend_api_key": "two words"},
        "key with a newline": NEW | {"backend_api_key": "abc\nX-Evil: 1"},
        "empty key": NEW | {"backend_api_key": ""},
        "huge key": NEW | {"backend_api_key": "k" * 513},
        "unknown field": NEW | {"role": "admin"},
    }
    for label, body in cases.items():
        response = await client.post("/api/models", json=body)
        assert response.status_code == 422, label
    assert await ManagedModel.all().count() == 3  # nothing was added


async def test_priority_and_idle_time_can_change_while_awake(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    token = await stack.api_key()
    await stack.chat(token, "b")
    assert model_state(stack, "b") == "awake"
    response = await client.patch("/api/models/b", json={"priority": 7, "idle_minutes": 2})
    assert response.status_code == 200
    assert (response.json()["priority"], response.json()["idle_minutes"]) == (7, 2)
    assert stack.container.manager.models["b"].spec.priority == 7
    assert (await client.get("/api/status")).json()["models"]["b"]["priority"] == 7
    assert (await ManagedModel.get(name="b")).priority == 7


async def test_where_a_model_runs_only_changes_while_it_is_idle(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    token = await stack.api_key()
    await stack.chat(token, "b")  # b is awake
    blocked = await client.patch("/api/models/b", json={"gpus": [2]})
    assert blocked.status_code == 422
    assert "put it to sleep first" in blocked.json()["detail"]
    assert stack.container.manager.models["b"].spec.gpus == frozenset({0})

    assert (await client.post("/api/models/b/sleep")).status_code == 204
    assert model_state(stack, "b") == "asleep"
    moved = await client.patch("/api/models/b", json={"gpus": [2]})
    assert moved.status_code == 200
    assert moved.json()["gpus"] == [2]


async def test_clearing_optional_fields(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await client.patch("/api/models/c", json={"served_name": "org/other"})
    assert (await ManagedModel.get(name="c")).served_name == "org/other"
    cleared = await client.patch("/api/models/c", json={"clear": ["served_name"]})
    assert cleared.json()["served_name"] is None
    assert (await client.patch("/api/models/c", json={"clear": ["url"]})).status_code == 422


async def test_renaming_into_a_taken_served_name_is_refused(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    response = await client.patch("/api/models/b", json={"served_name": "org/c"})
    assert response.status_code == 422


async def test_manual_sleep(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    token = await stack.api_key()
    assert (await client.post("/api/models/b/sleep")).status_code == 204  # already asleep: fine
    await stack.chat(token, "b")
    assert (await client.post("/api/models/b/sleep")).status_code == 204
    assert model_state(stack, "b") == "asleep"
    assert (await client.post("/api/models/ghost/sleep")).status_code == 404
    assert await AuditLog.filter(action="model.sleep", target="b").exists()


async def test_a_busy_model_cannot_be_slept_changed_or_removed(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    token = await stack.api_key()
    stack.fakes["b"].work_s = 0.8
    request = asyncio.create_task(stack.chat(token, "b"))
    await asyncio.sleep(0.3)  # the request is running on b
    assert (await client.post("/api/models/b/sleep")).status_code == 422
    assert (await client.delete("/api/models/b")).status_code == 422
    assert (await client.patch("/api/models/b", json={"gpus": [2]})).status_code == 422
    assert (await request).status_code == 200
    assert stack.ledger.violations == []


async def test_remove_a_model(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    token = await stack.api_key()
    assert (await client.delete("/api/models/c")).status_code == 204
    assert (await client.delete("/api/models/c")).status_code == 404
    assert await ManagedModel.filter(name="c").count() == 0
    assert (await stack.chat(token, "c")).status_code == 404
    listed = (await client.get("/api/models")).json()
    assert [m["name"] for m in listed["items"]] == ["a", "b"]
    assert "c" not in (await client.get("/api/status")).json()["models"]
    assert await AuditLog.filter(action="model.remove", target="c").exists()
    # the container itself is untouched, so it can be registered again
    assert (
        await client.post(
            "/api/models",
            json={
                "name": "c",
                "server": "this-server",
                "url": "http://127.0.0.1:9003",
                "gpus": [1],
                "served_name": "org/c",
            },
        )
    ).status_code == 201


async def test_awake_models_cannot_be_removed(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await stack.chat(await stack.api_key(), "b")
    assert (await client.delete("/api/models/b")).status_code == 422


async def test_connection_check(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    ok = (
        await client.post("/api/models/check", json={"url": NEW["url"], "served_name": "org/d"})
    ).json()
    assert ok["reachable"] is True
    assert ok["sleep_endpoints"] is True
    assert ok["state"] == "awake"
    assert ok["served_models"] == ["org/d"]
    assert ok["served_name_found"] is True
    assert ok["problems"] == []
    assert not is_asleep(stack, "d")  # checking changes nothing

    wrong = (
        await client.post("/api/models/check", json={"url": NEW["url"], "served_name": "org/zzz"})
    ).json()
    assert wrong["served_name_found"] is False
    assert any("org/d" in p for p in wrong["problems"])


async def test_connection_check_reports_a_missing_container(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    stack.dispatch.down.add(9)
    result = (await client.post("/api/models/check", json={"url": "http://127.0.0.1:9"})).json()
    assert result["reachable"] is False
    assert result["state"] is None
    assert any("cannot reach" in p for p in result["problems"])
    assert (await client.post("/api/models/check", json={"url": "ftp://nope"})).status_code == 422


async def test_models_list_is_paginated_and_searchable(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    page = (await client.get("/api/models?page_size=2")).json()
    assert (page["total"], page["pages"], len(page["items"])) == (3, 2, 2)
    assert (await client.get("/api/models?page=2&page_size=2")).json()["items"][0]["name"] == "c"
    by_served = (await client.get("/api/models?q=ORG/B")).json()
    assert [m["name"] for m in by_served["items"]] == ["b"]
    assert (await client.get("/api/models?q=zzz")).json()["total"] == 0


# --- the container's own API key, entered in the dashboard and stored in the database -------------

KEY = "vllm-secret-key-123"


async def test_a_model_that_needs_a_key_works_once_the_key_is_entered(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack()
    client = await admin(stack)
    stack.fakes["d"].api_key = KEY
    created = await client.post("/api/models", json=NEW | {"backend_api_key": KEY})
    assert created.status_code == 201
    assert created.json()["state"] == "asleep"  # the router could talk to the protected container
    assert created.json()["has_api_key"] is True
    assert (await ManagedModel.get(name="model-d")).backend_api_key == KEY  # stored in the database
    token = await stack.api_key()
    assert (
        await stack.chat(token, "model-d")
    ).status_code == 200  # and it sends the key on requests
    assert stack.fakes["d"].served == 1


async def test_without_the_key_a_protected_model_is_unusable(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    stack.fakes["d"].api_key = KEY
    created = await client.post("/api/models", json=NEW)
    assert created.json()["state"] == "down"
    assert created.json()["has_api_key"] is False
    assert (await stack.chat(await stack.api_key(), "model-d")).status_code == 503


async def test_the_key_is_never_sent_back_logged_or_audited(
    make_stack: StackFactory, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    stack = await make_stack()
    client = await admin(stack)
    stack.fakes["d"].api_key = KEY
    responses = [
        await client.post("/api/models", json=NEW | {"backend_api_key": KEY}),
        await client.get("/api/models"),
        await client.get("/api/models?q=model"),
        await client.get("/api/status"),
        await client.patch("/api/models/model-d", json={"priority": 2}),
        await client.post("/api/models/check", json={"url": NEW["url"], "backend_api_key": KEY}),
        await client.get("/api/audit?page_size=100"),
    ]
    await stack.chat(await stack.api_key(), "model-d")  # wakes it: the key is used on the wire
    for response in responses:
        assert KEY not in response.text
    assert KEY not in caplog.text
    audit = [str(e) for e in await AuditLog.all().values()]
    assert not any(KEY in entry for entry in audit)
    assert KEY not in repr(stack.container.manager.models["model-d"].spec)


async def test_the_key_can_be_replaced_or_removed_while_the_model_is_awake(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack()
    client = await admin(stack)
    stack.fakes["d"].api_key = KEY
    await client.post("/api/models", json=NEW | {"backend_api_key": KEY})
    token = await stack.api_key()
    assert (await stack.chat(token, "model-d")).status_code == 200
    assert model_state(stack, "model-d") == "awake"

    stack.fakes["d"].api_key = "rotated-key-456"  # the container was restarted with a new key
    rotated = await client.patch("/api/models/model-d", json={"backend_api_key": "rotated-key-456"})
    assert rotated.status_code == 200  # a key change does not need the model to be idle
    assert (await ManagedModel.get(name="model-d")).backend_api_key == "rotated-key-456"
    assert (await stack.chat(token, "model-d")).status_code == 200

    removed = await client.patch("/api/models/model-d", json={"clear": ["backend_api_key"]})
    assert removed.json()["has_api_key"] is False
    assert (await ManagedModel.get(name="model-d")).backend_api_key is None


async def test_changing_other_settings_keeps_the_stored_key(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    stack.fakes["d"].api_key = KEY
    await client.post("/api/models", json=NEW | {"backend_api_key": KEY})
    await client.patch("/api/models/model-d", json={"priority": 9})
    assert (await ManagedModel.get(name="model-d")).backend_api_key == KEY


async def test_connection_check_with_a_key(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    stack.fakes["d"].api_key = KEY
    body = {"url": NEW["url"], "served_name": "org/d"}

    none = (await client.post("/api/models/check", json=body)).json()
    assert none["reachable"] is True  # /health is open
    assert none["key_accepted"] is None
    assert any("wants an API key" in p for p in none["problems"])

    wrong = (
        await client.post("/api/models/check", json=body | {"backend_api_key": "nope-nope"})
    ).json()
    assert wrong["key_accepted"] is False
    assert any("refused the API key" in p for p in wrong["problems"])

    right = (await client.post("/api/models/check", json=body | {"backend_api_key": KEY})).json()
    assert right["key_accepted"] is True
    assert right["problems"] == []
    assert right["served_name_found"] is True
