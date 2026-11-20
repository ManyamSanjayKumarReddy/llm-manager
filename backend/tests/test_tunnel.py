"""Servers whose agent connects out: enrollment, the connection, and calls sent down it."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

import httpx
import pytest
import pytest_asyncio
import websockets
from websockets.exceptions import InvalidStatus

from llm_manager.core.routing import for_server
from llm_manager.db.models import AuditLog, Server
from tests.conftest import PORTS, Stack, StackFactory, eventually
from tests.fake_tunnel import FakeTunnelAgent, ServedApp
from tests.fakes import FakeAgent

AGENT_TOKEN = "a" * 40
SERVER = "this-server"


@dataclass
class Rig:
    stack: Stack
    admin: httpx.AsyncClient
    port: int
    agents: list[FakeTunnelAgent] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.port}/api/agent/connect"

    async def enroll(self, server: str = SERVER) -> str:
        response = await self.admin.post(f"/api/servers/{server}/tunnel")
        assert response.status_code == 201, response.text
        return str(response.json()["token"])

    async def connect(self, token: str, server: str = SERVER) -> FakeTunnelAgent:
        """An agent for the server, started and known to the hub."""
        control = FakeAgent(
            self.stack.dispatch, self.stack.ledger, self.stack.fakes, PORTS, AGENT_TOKEN
        )
        gpus = {"a": [0, 1], "b": [0], "c": [1], "d": [2]}
        for name, port in PORTS.items():
            control.seed(f"vllm-{name}", port, gpus[name])
        agent = FakeTunnelAgent(
            self.url,
            token,
            {PORTS[n]: f.app for n, f in self.stack.fakes.items()},
            control.app,
            AGENT_TOKEN,
        )
        await agent.start()
        self.agents.append(agent)

        async def known() -> bool:
            return self.stack.hub.info(server).agent_version is not None

        await eventually(known)
        return agent


RigFactory = Callable[..., Awaitable[Rig]]
Check = Callable[[], Awaitable[bool]]


@pytest_asyncio.fixture
async def make_rig(make_stack: StackFactory) -> AsyncIterator[RigFactory]:
    """The app served on a real port, with an admin logged in."""
    started: list[tuple[ServedApp, Rig]] = []

    async def _make(**overrides: object) -> Rig:
        stack = await make_stack(**overrides)
        await stack.create_user()
        admin = await stack.login()
        served = ServedApp(stack.app)
        rig = Rig(stack, admin, await served.start())
        started.append((served, rig))
        return rig

    yield _make
    for served, rig in started:
        for agent in rig.agents:
            await agent.stop()
        await served.stop()


def _chat_ids(agent: FakeTunnelAgent) -> list[int]:
    """Ids of the chat requests the agent was sent (health probes are left out)."""
    return [f["id"] for f in agent.received if f["t"] == "req" and "chat" in f["path"]]


def _request_arrived(agent: FakeTunnelAgent) -> Check:
    async def check() -> bool:
        ids = _chat_ids(agent)
        return bool(ids) and any(f["t"] == "end" and f["id"] == ids[-1] for f in agent.received)

    return check


async def test_enrolling_gives_a_token_once_and_marks_the_server(make_rig: RigFactory) -> None:
    rig = await make_rig()
    token = await rig.enroll()
    assert token.startswith("wkt_")
    listing = await rig.admin.get("/api/servers")
    server = {s["name"]: s for s in listing.json()}[SERVER]
    assert server["tunnel"] is True
    assert server["tunnel_connected"] is False
    assert server["has_agent"] is True
    assert token not in listing.text  # never shown again
    row = await Server.get(name=SERVER)
    assert row.tunnel_token_hash is not None
    assert row.tunnel_token_hash != token
    assert await AuditLog.filter(action="server.tunnel_enroll", target=SERVER).exists()


async def test_the_connection_needs_a_valid_token(make_rig: RigFactory) -> None:
    rig = await make_rig()
    await rig.enroll()
    for headers in ({}, {"Authorization": "Bearer wkt_wrong"}, {"Authorization": "Basic abc"}):
        with pytest.raises(InvalidStatus) as refused:
            await websockets.connect(rig.url, additional_headers=headers)
        assert refused.value.response.status_code == 403


async def test_a_connected_agent_is_shown_and_serves_requests(make_rig: RigFactory) -> None:
    rig = await make_rig()
    agent = await rig.connect(await rig.enroll())
    rig.stack.dispatch.seen.clear()

    listing = await rig.admin.get("/api/servers")
    server = {s["name"]: s for s in listing.json()}[SERVER]
    assert server["tunnel_connected"] is True
    assert server["tunnel_agent_version"] == "0.1.0"

    key = await rig.stack.api_key()
    answer = await rig.stack.chat(key, "a")
    assert answer.status_code == 200, answer.text
    assert answer.json()["served_by"] == "a"
    assert rig.stack.dispatch.seen == []  # nothing was called by address
    assert any(f["t"] == "req" and f["port"] == PORTS["a"] for f in agent.received)
    assert rig.stack.ledger.violations == []


async def test_streamed_answers_arrive_whole(make_rig: RigFactory) -> None:
    rig = await make_rig()
    await rig.connect(await rig.enroll())
    key = await rig.stack.api_key()
    answer = await rig.stack.chat(key, "b", stream=True)
    assert answer.status_code == 200
    assert "chunk0" in answer.text
    assert "chunk2" in answer.text
    assert answer.text.rstrip().endswith("[DONE]")


async def test_a_large_request_is_split_and_put_back_together(make_rig: RigFactory) -> None:
    rig = await make_rig()
    agent = await rig.connect(await rig.enroll())
    key = await rig.stack.api_key()
    big = "x" * 700_000
    answer = await rig.stack.chat(key, "a", messages=[{"role": "user", "content": big}])
    assert answer.status_code == 200
    assert rig.stack.fakes["a"].last_body["messages"][0]["content"] == big
    last = max(f["id"] for f in agent.received if f["t"] == "req" and f["port"] == PORTS["a"])
    frames = [f for f in agent.received if f["t"] == "data" and f["id"] == last]
    assert len(frames) >= 3  # the body travelled in several frames


async def test_containers_are_controlled_through_the_connection(make_rig: RigFactory) -> None:
    rig = await make_rig()
    agent = await rig.connect(await rig.enroll())
    listed = await rig.admin.get(f"/api/servers/{SERVER}/containers")
    assert listed.status_code == 200, listed.text
    assert {c["name"] for c in listed.json()["items"]} >= {"vllm-a", "vllm-b"}
    assert any(f["t"] == "req" and f["target"] == "agent" for f in agent.received)
    assert (await rig.admin.get(f"/api/servers/{SERVER}/host")).status_code == 200
    logs = await rig.admin.get(f"/api/servers/{SERVER}/containers/vllm-a/logs")
    assert logs.status_code == 200


async def test_container_calls_say_so_when_the_agent_is_not_connected(
    make_rig: RigFactory,
) -> None:
    rig = await make_rig()
    await rig.enroll()
    response = await rig.admin.get(f"/api/servers/{SERVER}/containers")
    assert response.status_code == 503
    assert "not connected" in response.json()["detail"]


async def test_losing_the_connection_ends_calls_in_flight(make_rig: RigFactory) -> None:
    rig = await make_rig()
    agent = await rig.connect(await rig.enroll())
    key = await rig.stack.api_key()
    pending = asyncio.create_task(rig.stack.chat(key, "a", work_s=5))
    await eventually(_request_arrived(agent))
    await agent.stop()  # the server went away mid-request
    answer = await asyncio.wait_for(pending, 5)
    assert answer.status_code in {502, 503}

    async def gone() -> bool:
        return not rig.stack.hub.info(SERVER).connected

    await eventually(gone)


async def test_giving_up_on_a_call_tells_the_agent_to_stop(make_rig: RigFactory) -> None:
    rig = await make_rig()
    agent = await rig.connect(await rig.enroll())
    rig.stack.fakes["a"].sleeping = False  # awake, so the request really takes its 5 s
    call = asyncio.create_task(
        rig.stack.container.http.post(
            f"http://127.0.0.1:{PORTS['a']}/v1/chat/completions",
            json={"model": "org/a", "messages": [], "work_s": 5},
            extensions=for_server(SERVER),
        )
    )
    await eventually(_request_arrived(agent))
    call.cancel()
    await asyncio.gather(call, return_exceptions=True)

    async def told() -> bool:
        return _chat_ids(agent)[-1] in agent.cancelled

    await eventually(told)


async def test_a_second_agent_takes_over_from_the_first(make_rig: RigFactory) -> None:
    rig = await make_rig()
    token = await rig.enroll()
    first = await rig.connect(token)
    second = await rig.connect(token)
    await first.wait_closed()
    assert first.close_code == 4000
    before = len(first.received)
    key = await rig.stack.api_key()
    answer = await rig.stack.chat(key, "c")
    assert answer.status_code == 200
    assert any(f["t"] == "req" and f["port"] == PORTS["c"] for f in second.received)
    assert len(first.received) == before  # nothing more was sent to the replaced connection


async def test_a_new_token_cuts_off_the_old_one(make_rig: RigFactory) -> None:
    rig = await make_rig()
    old = await rig.enroll()
    agent = await rig.connect(old)
    new = await rig.enroll()
    await agent.wait_closed()
    with pytest.raises(InvalidStatus):
        await websockets.connect(rig.url, additional_headers={"Authorization": f"Bearer {old}"})
    await rig.connect(new)
    assert rig.stack.hub.info(SERVER).connected


async def test_revoking_disconnects_and_forgets_the_link(make_rig: RigFactory) -> None:
    rig = await make_rig()
    token = await rig.enroll()
    agent = await rig.connect(token)
    revoked = await rig.admin.delete(f"/api/servers/{SERVER}/tunnel")
    assert revoked.status_code == 200
    assert revoked.json()["tunnel"] is False
    await agent.wait_closed()
    with pytest.raises(InvalidStatus):
        await websockets.connect(rig.url, additional_headers={"Authorization": f"Bearer {token}"})
    assert (await rig.admin.delete(f"/api/servers/{SERVER}/tunnel")).status_code == 422
    assert await AuditLog.filter(action="server.tunnel_revoke").exists()


async def test_a_server_that_connects_out_takes_no_address(make_rig: RigFactory) -> None:
    rig = await make_rig()
    await rig.enroll()
    response = await rig.admin.patch(
        f"/api/servers/{SERVER}",
        json={"agent_url": "https://agent.test/agent", "agent_token": "t" * 40},
    )
    assert response.status_code == 422
    assert "connects out" in response.json()["detail"]


async def test_enrolling_replaces_a_stored_address(make_rig: RigFactory) -> None:
    rig = await make_rig()
    patched = await rig.admin.patch(
        f"/api/servers/{SERVER}",
        json={"agent_url": "https://agent.test/agent", "agent_token": "t" * 40},
    )
    assert patched.status_code == 200
    await rig.enroll()
    row = await Server.get(name=SERVER)
    assert row.agent_url is None
    assert row.agent_token is None


async def test_only_admins_can_enroll(make_rig: RigFactory) -> None:
    rig = await make_rig()
    anonymous = rig.stack.anonymous()
    assert (await anonymous.post(f"/api/servers/{SERVER}/tunnel")).status_code in {401, 403}


async def test_models_on_other_servers_are_still_reached_by_address(
    make_rig: RigFactory,
) -> None:
    rig = await make_rig()
    await rig.enroll("gpu-box-2")  # another server connects out; this-server does not
    key = await rig.stack.api_key()
    answer = await rig.stack.chat(key, "a")
    assert answer.status_code == 200
    assert PORTS["a"] in rig.stack.dispatch.seen
