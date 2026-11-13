"""Servers: the registered machines that models are placed on."""

import httpx

from llm_manager.db.models import ManagedModel, Role
from tests.conftest import PORTS, Stack, StackFactory, model_state

NEW_D = {
    "name": "model-d",
    "server": "gpu-box-2",
    "url": f"http://127.0.0.1:{PORTS['d']}",
    "served_name": "org/d",
    "gpus": [0],  # GPU 0 of the *other* machine: not the GPU model b uses
}


async def admin(stack: Stack) -> httpx.AsyncClient:
    await stack.create_user()
    return await stack.login()


async def test_servers_list_with_their_models(make_stack: StackFactory) -> None:
    client = await admin(await make_stack())
    servers = {s["name"]: s for s in (await client.get("/api/servers")).json()}
    assert servers["this-server"]["gpu_count"] == 8
    assert servers["this-server"]["models"] == ["a", "b", "c"]
    assert servers["gpu-box-2"]["models"] == []


async def test_add_resize_and_remove_a_server(make_stack: StackFactory) -> None:
    client = await admin(await make_stack())
    added = await client.post("/api/servers", json={"name": "box-3", "gpu_count": 4})
    assert added.status_code == 201
    assert (
        await client.post("/api/servers", json={"name": "box-3", "gpu_count": 1})
    ).status_code == 422
    assert (await client.patch("/api/servers/box-3", json={"gpu_count": 2})).json()[
        "gpu_count"
    ] == 2
    assert (await client.delete("/api/servers/box-3")).status_code == 204
    assert (await client.delete("/api/servers/box-3")).status_code == 404


async def test_bad_servers_are_rejected(make_stack: StackFactory) -> None:
    client = await admin(await make_stack())
    for body in (
        {"name": "Has Spaces", "gpu_count": 2},
        {"name": "ok", "gpu_count": 0},
        {"name": "ok", "gpu_count": 17},
        {"name": "ok", "gpu_count": 2, "extra": 1},
    ):
        assert (await client.post("/api/servers", json=body)).status_code == 422, body


async def test_a_server_in_use_cannot_shrink_or_go(make_stack: StackFactory) -> None:
    client = await admin(await make_stack())
    assert (await client.delete("/api/servers/this-server")).status_code == 422  # has models
    assert (
        await client.patch("/api/servers/this-server", json={"gpu_count": 1})
    ).status_code == 422
    assert (
        await client.patch("/api/servers/this-server", json={"gpu_count": 2})
    ).status_code == 200


async def test_only_admins_manage_servers(make_stack: StackFactory) -> None:
    stack = await make_stack()
    await stack.create_user("viewer1", Role.VIEWER, "a-long-passphrase")
    viewer = await stack.login("viewer1", "a-long-passphrase")
    assert (await viewer.get("/api/servers")).status_code == 403
    assert (
        await viewer.post("/api/servers", json={"name": "x", "gpu_count": 1})
    ).status_code == 403


async def test_a_model_needs_a_registered_server_with_that_gpu(make_stack: StackFactory) -> None:
    client = await admin(await make_stack())
    nowhere = await client.post("/api/models", json=NEW_D | {"server": "nope"})
    assert nowhere.status_code == 422
    too_big = await client.post("/api/models", json=NEW_D | {"gpus": [2]})  # gpu-box-2 has 0 and 1
    assert too_big.status_code == 422
    assert (
        await client.post("/api/models", json={k: v for k, v in NEW_D.items() if k != "server"})
    ).status_code == 422
    assert await ManagedModel.all().count() == 3


async def test_same_gpu_number_on_another_server_is_not_shared(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    created = await client.post("/api/models", json=NEW_D)
    assert created.status_code == 201
    assert created.json()["server"] == "gpu-box-2"
    token = await stack.api_key()
    assert (await stack.chat(token, "b")).status_code == 200  # b uses GPU 0 of this-server
    assert (await stack.chat(token, "model-d")).status_code == 200  # GPU 0 of gpu-box-2
    assert model_state(stack, "b") == model_state(stack, "model-d") == "awake"


async def test_same_gpu_number_on_the_same_server_still_swaps(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    assert (
        await client.post("/api/models", json=NEW_D | {"server": "this-server"})
    ).status_code == 201
    token = await stack.api_key()
    assert (await stack.chat(token, "b")).status_code == 200
    assert (await stack.chat(token, "model-d")).status_code == 200
    assert model_state(stack, "b") == "asleep"
    assert model_state(stack, "model-d") == "awake"


async def test_a_model_can_move_to_another_server_while_idle(make_stack: StackFactory) -> None:
    client = await admin(await make_stack())
    moved = await client.patch("/api/models/c", json={"server": "gpu-box-2", "gpus": [1]})
    assert moved.status_code == 200
    assert moved.json()["server"] == "gpu-box-2"
    assert (await ManagedModel.get(name="c").prefetch_related("server")).server.name == "gpu-box-2"


async def test_a_server_can_describe_its_gpus(make_stack: StackFactory) -> None:
    client = await admin(await make_stack())
    added = await client.post(
        "/api/servers", json={"name": "box-3", "gpu_count": 2, "gpu_type": "RTX 4060 Ti 16 GB"}
    )
    assert added.json()["gpu_type"] == "RTX 4060 Ti 16 GB"
    only_type = await client.patch("/api/servers/box-3", json={"gpu_type": "RTX 5060 Ti"})
    assert (only_type.json()["gpu_type"], only_type.json()["gpu_count"]) == ("RTX 5060 Ti", 2)
    cleared = await client.patch("/api/servers/box-3", json={"gpu_type": ""})
    assert cleared.json()["gpu_type"] is None
