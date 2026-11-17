"""Controlling containers through a server's agent, and keeping the scheduler in step."""

import asyncio

import httpx
from fastapi import FastAPI

from llm_manager.db.models import AuditLog, ManagedModel, Role, Server
from tests.conftest import PORTS, Stack, StackFactory, model_state, until_busy
from tests.fakes import FakeAgent

TOKEN = "a" * 40
AGENT_URL = "https://agent.test/agent"
LONG = 5.0


async def admin(stack: Stack) -> httpx.AsyncClient:
    await stack.create_user()
    return await stack.login()


async def with_agent(
    stack: Stack, client: httpx.AsyncClient, server: str = "this-server"
) -> FakeAgent:
    """Give ``server`` an agent that knows the containers of models a, b, c and d."""
    agent = FakeAgent(stack.dispatch, stack.ledger, stack.fakes, PORTS, TOKEN)
    gpus = {"a": [0, 1], "b": [0], "c": [1], "d": [2]}
    for name, port in PORTS.items():
        agent.seed(f"vllm-{name}", port, gpus[name])
    outer = FastAPI()
    outer.mount("/agent", agent.app)  # like the web server in front of the real agent
    stack.dispatch.add_host("agent.test", outer)
    patched = await client.patch(
        f"/api/servers/{server}", json={"agent_url": AGENT_URL, "agent_token": TOKEN}
    )
    assert patched.status_code == 200, patched.text
    return agent


async def settle(stack: Stack, name: str, state: str) -> None:
    for _ in range(100):
        if model_state(stack, name) == state:
            return
        await asyncio.sleep(0.05)
    assert model_state(stack, name) == state


def body(**changes: object) -> dict[str, object]:
    return {
        "name": "vllm-new",
        "model": "org/new",
        "image": "vllm/vllm-openai:v0.10.1",
        "port": PORTS["d"],
        "gpus": [2],
        "cache_dir": "/root/.cache/huggingface",
        **changes,
    }


# ------------------------------------------------------------------ server settings
async def test_a_server_can_be_given_an_agent_and_the_token_is_never_returned(
    make_stack: StackFactory,
) -> None:
    client = await admin(await make_stack())
    added = await client.post(
        "/api/servers",
        json={"name": "box-3", "gpu_count": 2, "agent_url": AGENT_URL, "agent_token": TOKEN},
    )
    assert added.status_code == 201
    assert added.json()["agent_url"] == AGENT_URL
    assert added.json()["has_agent"] is True
    assert TOKEN not in added.text
    assert TOKEN not in (await client.get("/api/servers")).text
    row = await Server.get(name="box-3")
    assert row.agent_token == TOKEN


async def test_bad_agent_settings_are_refused(make_stack: StackFactory) -> None:
    client = await admin(await make_stack())
    for extra in (
        {"agent_url": "http://gpu-box.example.com"},  # the token would cross the network in clear
        {"agent_url": "ftp://x"},
        {"agent_url": "https://user:pw@x.example.com"},
        {"agent_url": AGENT_URL},  # an address without a token
        {"agent_token": TOKEN},  # a token without an address
        {"agent_url": AGENT_URL, "agent_token": "short"},
    ):
        response = await client.post("/api/servers", json={"name": "bad", "gpu_count": 1, **extra})
        assert response.status_code == 422, extra
    local = await client.post(
        "/api/servers",
        json={
            "name": "local",
            "gpu_count": 1,
            "agent_url": "http://127.0.0.1:8050",
            "agent_token": TOKEN,
        },
    )
    assert local.status_code == 201


async def test_removing_the_agent_forgets_its_token(make_stack: StackFactory) -> None:
    client = await admin(await make_stack())
    await client.patch(
        "/api/servers/gpu-box-2", json={"agent_url": AGENT_URL, "agent_token": TOKEN}
    )
    cleared = await client.patch("/api/servers/gpu-box-2", json={"agent_url": ""})
    assert cleared.json()["has_agent"] is False
    row = await Server.get(name="gpu-box-2")
    assert (row.agent_url, row.agent_token) == (None, None)


async def test_a_server_without_an_agent_says_so(make_stack: StackFactory) -> None:
    client = await admin(await make_stack())
    response = await client.get("/api/servers/gpu-box-2/containers")
    assert response.status_code == 422
    assert "no agent" in response.json()["detail"]


async def test_only_admins_may_control_containers(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await with_agent(stack, client)
    await stack.create_user("bob", Role.VIEWER, "another-long-password")
    bob = await stack.login("bob", "another-long-password")
    assert (await bob.get("/api/servers/this-server/containers")).status_code == 403
    assert (await bob.post("/api/servers/this-server/containers/vllm-a/stop")).status_code == 403
    assert (await stack.anonymous().get("/api/servers/this-server/host")).status_code == 401


# ------------------------------------------------------------------------- reading
async def test_containers_are_listed_with_their_registered_model(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await with_agent(stack, client)
    page = (await client.get("/api/servers/this-server/containers")).json()
    by_name = {c["name"]: c for c in page["items"]}
    assert page["total"] == 4
    assert by_name["vllm-a"]["registered_as"] == "a"  # matched by the port in its URL
    assert by_name["vllm-a"]["model_state"] == "asleep"
    assert by_name["vllm-d"]["registered_as"] is None
    assert by_name["vllm-d"]["model_state"] is None

    paged = (await client.get("/api/servers/this-server/containers?page=2&page_size=3")).json()
    assert [c["name"] for c in paged["items"]] == ["vllm-d"]


async def test_host_figures_and_logs(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await with_agent(stack, client)
    host = (await client.get("/api/servers/this-server/host")).json()
    assert host["gpus"][0]["memory_total_mb"] == 16000
    logs = (await client.get("/api/servers/this-server/containers/vllm-a/logs?tail=30")).json()
    assert logs["text"] == "last 30 lines\n"
    assert (
        await client.get("/api/servers/this-server/containers/vllm-a/logs?tail=0")
    ).status_code == 422


async def test_an_unreachable_agent_is_a_clear_503(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await client.patch(
        "/api/servers/this-server", json={"agent_url": "https://nobody.test", "agent_token": TOKEN}
    )
    response = await client.get("/api/servers/this-server/containers")
    assert response.status_code == 503
    assert "cannot reach the agent" in response.json()["detail"]


async def test_a_refused_token_is_reported(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await with_agent(stack, client)
    await client.patch("/api/servers/this-server", json={"agent_token": "b" * 40})
    response = await client.get("/api/servers/this-server/containers")
    assert response.status_code == 422
    assert "refused the token" in response.json()["detail"]


# ---------------------------------------------------------------- stop, start, restart
async def test_stopping_a_sleeping_models_container_marks_it_down_and_starting_it_back_asleep(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack()
    client = await admin(stack)
    agent = await with_agent(stack, client)

    stopped = await client.post("/api/servers/this-server/containers/vllm-b/stop")
    assert stopped.status_code == 200
    assert stopped.json()["running"] is False
    assert model_state(stack, "b") == "down"  # at once, not after the next health check

    started = await client.post("/api/servers/this-server/containers/vllm-b/start")
    assert started.status_code == 200
    assert started.json()["registered_as"] == "b"
    await settle(stack, "b", "asleep")  # a fresh container starts awake; Wakeful sleeps it
    assert stack.ledger.violations == []
    assert agent.calls == [("stop", "vllm-b"), ("start", "vllm-b")]


async def test_restarting_an_awake_idle_model_keeps_it_serving(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await with_agent(stack, client)
    token = await stack.api_key()
    assert (await stack.chat(token, "b")).status_code == 200
    assert model_state(stack, "b") == "awake"

    restarted = await client.post("/api/servers/this-server/containers/vllm-b/restart")
    assert restarted.status_code == 200
    # the fresh container came back healthy and awake, which is what the scheduler believes too
    assert model_state(stack, "b") == "awake"
    assert (await stack.chat(token, "b")).status_code == 200
    assert stack.ledger.violations == []


async def test_a_container_is_not_stopped_or_restarted_while_its_model_is_busy(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack()
    client = await admin(stack)
    agent = await with_agent(stack, client)
    token = await stack.api_key()
    running = asyncio.create_task(stack.chat(token, "b", work_s=LONG))
    await until_busy(stack, "b")

    for verb in ("stop", "restart"):
        refused = await client.post(f"/api/servers/this-server/containers/vllm-b/{verb}")
        assert refused.status_code == 422, verb
        assert "running" in refused.json()["detail"]
    assert agent.calls == []  # the agent was never asked
    assert model_state(stack, "b") == "awake"
    running.cancel()
    await asyncio.gather(running, return_exceptions=True)


async def test_a_container_without_a_model_can_be_stopped_freely(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack()
    client = await admin(stack)
    agent = await with_agent(stack, client)
    response = await client.post("/api/servers/this-server/containers/vllm-d/stop")
    assert response.status_code == 200
    assert response.json()["registered_as"] is None
    assert agent.calls == [("stop", "vllm-d")]


async def test_an_unknown_container_is_a_404(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await with_agent(stack, client)
    for method, path in (
        ("POST", "/containers/ghost/stop"),
        ("POST", "/containers/ghost/start"),
        ("DELETE", "/containers/ghost"),
        ("GET", "/containers/ghost/logs"),
    ):
        response = await client.request(method, f"/api/servers/this-server{path}")
        assert response.status_code == 404, path


# -------------------------------------------------------------------------- remove
async def test_removing_a_container_with_a_model_needs_confirmation(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack()
    client = await admin(stack)
    agent = await with_agent(stack, client)

    refused = await client.delete("/api/servers/this-server/containers/vllm-b")
    assert refused.status_code == 422
    assert "removes that model" in refused.json()["detail"]
    assert "b" in stack.container.manager.models
    assert "vllm-b" in agent.containers

    removed = await client.delete("/api/servers/this-server/containers/vllm-b?remove_model=true")
    assert removed.status_code == 204
    assert "vllm-b" not in agent.containers
    assert "b" not in stack.container.manager.models
    assert not await ManagedModel.filter(name="b").exists()
    entry = await AuditLog.filter(action="container.remove").first()
    assert entry is not None
    assert entry.target == "this-server/vllm-b"
    assert "'b'" in (entry.detail or "")


async def test_removing_an_awake_idle_models_container_works(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    agent = await with_agent(stack, client)
    token = await stack.api_key()
    assert (await stack.chat(token, "c")).status_code == 200
    assert model_state(stack, "c") == "awake"
    removed = await client.delete("/api/servers/this-server/containers/vllm-c?remove_model=true")
    assert removed.status_code == 204
    assert "vllm-c" not in agent.containers
    assert "c" not in stack.container.manager.models


async def test_a_busy_models_container_is_not_removed(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    agent = await with_agent(stack, client)
    token = await stack.api_key()
    running = asyncio.create_task(stack.chat(token, "b", work_s=LONG))
    await until_busy(stack, "b")
    refused = await client.delete("/api/servers/this-server/containers/vllm-b?remove_model=true")
    assert refused.status_code == 422
    assert "vllm-b" in agent.containers
    assert "b" in stack.container.manager.models
    running.cancel()
    await asyncio.gather(running, return_exceptions=True)


async def test_removing_a_container_nobody_uses_needs_no_confirmation(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack()
    client = await admin(stack)
    agent = await with_agent(stack, client)
    assert (await client.delete("/api/servers/this-server/containers/vllm-d")).status_code == 204
    assert "vllm-d" not in agent.containers


# -------------------------------------------------------------------------- create
async def test_creating_a_container_and_registering_it_as_a_model(make_stack: StackFactory) -> None:
    stack = await make_stack(models=("a", "b", "c"))
    client = await admin(stack)
    agent = await with_agent(stack, client)
    del agent.containers["vllm-d"]  # the fake vLLM on that port stands in for the new container

    created = await client.post(
        "/api/servers/this-server/containers",
        json=body(
            api_key="sk-container-key",
            hf_token="hf_secret",
            register_as={"name": "model-d", "url": f"http://127.0.0.1:{PORTS['d']}", "priority": 3},
        ),
    )
    assert created.status_code == 201, created.text
    assert created.json()["registered_as"] == "model-d"
    assert "sk-container-key" not in created.text
    assert "hf_secret" not in created.text

    sent = agent.created[0]
    assert sent["api_key"] == "sk-container-key"  # the agent gets the real secrets
    assert sent["hf_token"] == "hf_secret"
    assert "register_as" not in sent

    row = await ManagedModel.get(name="model-d")
    assert row.container_name == "vllm-new"
    assert row.priority == 3
    assert row.backend_api_key == "sk-container-key"  # Wakeful can reach the container
    assert row.gpus == [2]
    assert model_state(stack, "model-d") == "asleep"  # an awake new container is put to sleep
    assert (await AuditLog.filter(action="container.create").first()) is not None
    audit = " ".join(
        f"{e.target} {e.detail}" for e in await AuditLog.filter(action="container.create")
    )
    assert "sk-container-key" not in audit
    assert "hf_secret" not in audit


async def test_creating_a_container_without_a_model(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    agent = await with_agent(stack, client)
    del agent.containers["vllm-d"]
    created = await client.post("/api/servers/this-server/containers", json=body())
    assert created.status_code == 201
    assert created.json()["registered_as"] is None
    assert not await ManagedModel.filter(container_name="vllm-new").exists()


async def test_a_clashing_model_name_is_refused_before_a_container_is_made(
    make_stack: StackFactory,
) -> None:
    stack = await make_stack()
    client = await admin(stack)
    agent = await with_agent(stack, client)
    del agent.containers["vllm-d"]
    response = await client.post(
        "/api/servers/this-server/containers",
        json=body(register_as={"name": "a", "url": f"http://127.0.0.1:{PORTS['d']}"}),
    )
    assert response.status_code == 422
    assert agent.created == []


async def test_gpus_the_server_does_not_have_are_refused(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    agent = await with_agent(stack, client, server="gpu-box-2")
    response = await client.post("/api/servers/gpu-box-2/containers", json=body(gpus=[0, 5]))
    assert response.status_code == 422
    assert "GPU" in response.json()["detail"]
    assert agent.created == []


async def test_the_agents_own_refusals_reach_the_admin(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await with_agent(stack, client)
    response = await client.post(
        "/api/servers/this-server/containers", json=body(image="evil/miner:1")
    )
    assert response.status_code == 422
    assert "only these repositories" in response.json()["detail"]


async def test_malformed_create_requests_are_refused(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    agent = await with_agent(stack, client)
    bad: list[dict[str, object]] = [
        {"name": "bad name"},
        {"model": "--evil"},
        {"port": 80},
        {"gpus": []},
        {"memory_share": 2},
        {"unknown": 1},
    ]
    for changes in bad:
        response = await client.post("/api/servers/this-server/containers", json=body(**changes))
        assert response.status_code == 422, changes
    assert agent.created == []


# ------------------------------------------------------------- linking models by hand
async def test_a_model_can_be_linked_to_a_container_and_unlinked(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await with_agent(stack, client)
    linked = await client.patch("/api/models/a", json={"container": "vllm-a"})
    assert linked.status_code == 200
    assert linked.json()["container"] == "vllm-a"

    clash = await client.patch("/api/models/b", json={"container": "vllm-a"})
    assert clash.status_code == 422
    assert "already runs" in clash.json()["detail"]

    cleared = await client.patch("/api/models/a", json={"clear": ["container"]})
    assert cleared.json()["container"] is None


async def test_linking_beats_guessing_by_port(make_stack: StackFactory) -> None:
    stack = await make_stack()
    client = await admin(stack)
    await with_agent(stack, client)
    # model b's URL says port 9002, but it is explicitly linked to the container on 9003
    await client.patch("/api/models/b", json={"container": "vllm-c"})
    by_name = {
        c["name"]: c
        for c in (await client.get("/api/servers/this-server/containers")).json()["items"]
    }
    assert by_name["vllm-c"]["registered_as"] == "b"
