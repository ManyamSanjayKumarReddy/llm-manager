"""The outbound connection: the agent dials a (fake) Wakeful and answers what it is sent."""

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import uvicorn
import websockets
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError
from websockets.asyncio.server import ServerConnection

from tests.fakes import FakeDocker, FakeHost
from wakeful_agent import tunnel as tunnel_module
from wakeful_agent.app import create_app
from wakeful_agent.settings import Settings
from wakeful_agent.tunnel import CHUNK_BYTES, Tunnel

CONNECT_TOKEN = "c" * 40
STAND_IN_PORT = 0  # filled in by the fixture


class FakeWakeful:
    """Accepts the agent's connection and plays Wakeful's part."""

    def __init__(self) -> None:
        self.headers: list[dict[str, str]] = []
        self.hellos: list[dict[str, Any]] = []
        self.connections: asyncio.Queue[ServerConnection] = asyncio.Queue()
        self._frames: dict[int, asyncio.Queue[dict[str, Any]]] = {}
        self._ids = iter(range(1, 10_000))
        self._server: Any = None
        self.port = 0

    async def start(self) -> None:
        self._server = await websockets.serve(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self._server.close()
        await self._server.wait_closed()

    async def _handle(self, ws: ServerConnection) -> None:
        self.headers.append(dict(ws.request.headers.raw_items()) if ws.request else {})
        await self.connections.put(ws)
        async for raw in ws:
            frame = json.loads(raw)
            if frame["t"] == "hello":
                self.hellos.append(frame)
            else:
                self._frames.setdefault(frame["id"], asyncio.Queue()).put_nowait(frame)

    async def call(
        self,
        ws: ServerConnection,
        *,
        target: str,
        path: str,
        method: str = "GET",
        port: int | None = None,
        body: bytes = b"",
        headers: list[list[str]] | None = None,
        end: bool = True,
    ) -> int:
        """Send one request; returns its id."""
        call_id = next(self._ids)
        self._frames[call_id] = asyncio.Queue()
        await ws.send(
            json.dumps(
                {
                    "t": "req",
                    "id": call_id,
                    "target": target,
                    "port": port,
                    "method": method,
                    "path": path,
                    "headers": headers or [["accept", "*/*"], ["host", "elsewhere"]],
                }
            )
        )
        if body:
            await ws.send(
                json.dumps({"t": "data", "id": call_id, "b": base64.b64encode(body).decode()})
            )
        if end:
            await ws.send(json.dumps({"t": "end", "id": call_id}))
        return call_id

    async def frame(self, call_id: int) -> dict[str, Any]:
        return await asyncio.wait_for(self._frames[call_id].get(), 5.0)

    async def answer(self, call_id: int) -> tuple[dict[str, Any], bytes]:
        """The head and the whole body of an answer (raises on an error frame)."""
        head = await self.frame(call_id)
        assert head["t"] == "head", head
        body = b""
        while True:
            frame = await self.frame(call_id)
            if frame["t"] == "data":
                body += base64.b64decode(frame["b"])
            else:
                assert frame["t"] == "end", frame
                return head, body


class StandIn:
    """A vLLM stand-in on a real port: echoes, streams slowly, and notices dropped callers."""

    def __init__(self) -> None:
        self.hits: list[tuple[str, str, dict[str, str], bytes]] = []
        self.stream_started = asyncio.Event()
        self.stream_dropped = asyncio.Event()
        self.app = FastAPI()
        self.app.add_api_route("/echo", self._echo, methods=["GET", "POST"])
        self.app.add_api_route("/big", self._big)
        self.app.add_api_route("/slow", self._slow)

    async def _echo(self, request: Request) -> JSONResponse:
        body = await request.body()
        self.hits.append((request.method, request.url.path, dict(request.headers), body))
        return JSONResponse({"echo": body.decode()})

    async def _big(self) -> StreamingResponse:
        async def parts() -> AsyncIterator[bytes]:
            yield b"a" * (CHUNK_BYTES * 2 + 5)

        return StreamingResponse(parts(), media_type="application/octet-stream")

    async def _slow(self) -> StreamingResponse:
        async def parts() -> AsyncIterator[bytes]:
            try:
                for i in range(100):
                    self.stream_started.set()
                    yield f"data: {i}\n\n".encode()
                    await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                self.stream_dropped.set()
                raise

        return StreamingResponse(parts(), media_type="text/event-stream")


@pytest_asyncio.fixture
async def wakeful() -> AsyncIterator[FakeWakeful]:
    hub = FakeWakeful()
    await hub.start()
    yield hub
    await hub.stop()


@pytest_asyncio.fixture
async def stand_in() -> AsyncIterator[tuple[StandIn, int]]:
    thing = StandIn()
    server = uvicorn.Server(
        uvicorn.Config(thing.app, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
    )
    task = asyncio.create_task(server.serve())
    while not server.started:  # noqa: ASYNC110 - uvicorn offers no event to wait on
        await asyncio.sleep(0.01)
    port = int(server.servers[0].sockets[0].getsockname()[1])
    yield thing, port
    server.should_exit = True
    await task


def make_settings(wakeful: FakeWakeful, cache_root: Path, **extra: Any) -> Settings:
    return Settings(
        connect_url=f"ws://127.0.0.1:{wakeful.port}/api/agent/connect",
        connect_token=CONNECT_TOKEN,
        cache_roots=[cache_root],
        **extra,
    )


@pytest_asyncio.fixture
async def running(
    wakeful: FakeWakeful, cache_root: Path, docker: FakeDocker, stand_in: tuple[StandIn, int]
) -> AsyncIterator[tuple[Tunnel, ServerConnection]]:
    """The agent, connected to the fake Wakeful. Its docker knows one container on the stand-in."""
    _, port = stand_in
    docker.containers["vllm-a"] = await _container(docker, cache_root, port)
    settings = make_settings(wakeful, cache_root)
    tunnel = Tunnel(settings, create_app(settings, docker, FakeHost()), docker)
    task = asyncio.create_task(tunnel.run())
    ws = await asyncio.wait_for(wakeful.connections.get(), 5)
    await asyncio.wait_for(tunnel.connected.wait(), 5)
    yield tunnel, ws
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _container(docker: FakeDocker, cache_root: Path, port: int) -> Any:
    from wakeful_agent.spec import ContainerSpec, build_run

    settings = Settings(token="t" * 40, cache_roots=[cache_root])
    spec = ContainerSpec(
        name="vllm-a",
        model="org/a",
        image="vllm/vllm-openai:v0.10.1",
        port=port,
        gpus=[0],
        cache_dir=str(cache_root / "hf"),
    )
    await docker.run(build_run(spec, settings))
    return docker.containers["vllm-a"]


# ---------------------------------------------------------------- connecting


async def test_it_connects_with_the_token_and_says_hello(
    wakeful: FakeWakeful, running: tuple[Tunnel, ServerConnection]
) -> None:
    assert wakeful.headers[0]["Authorization"] == f"Bearer {CONNECT_TOKEN}"
    for _ in range(100):
        if wakeful.hellos:
            break
        await asyncio.sleep(0.02)
    assert wakeful.hellos[0]["version"]


async def test_it_reconnects_after_the_connection_drops(
    wakeful: FakeWakeful,
    running: tuple[Tunnel, ServerConnection],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tunnel_module, "_MIN_DELAY_S", 0.05)
    _, first = running
    await first.close()
    again = await asyncio.wait_for(wakeful.connections.get(), 10)
    assert again is not first


# ---------------------------------------------------------------- the agent's own endpoints


async def test_its_own_endpoints_are_answered_without_a_token_from_wakeful(
    wakeful: FakeWakeful, running: tuple[Tunnel, ServerConnection]
) -> None:
    _, ws = running
    call = await wakeful.call(ws, target="agent", path="/containers")
    head, body = await wakeful.answer(call)
    assert head["status"] == 200
    assert [c["name"] for c in json.loads(body)] == ["vllm-a"]


async def test_changes_go_through_the_same_rules_as_over_http(
    wakeful: FakeWakeful, running: tuple[Tunnel, ServerConnection], docker: FakeDocker
) -> None:
    _, ws = running
    call = await wakeful.call(ws, target="agent", path="/containers/vllm-a/stop", method="POST")
    head, _ = await wakeful.answer(call)
    assert head["status"] == 200
    assert docker.containers["vllm-a"].running is False
    missing = await wakeful.call(
        ws, target="agent", path="/containers/production-db/stop", method="POST"
    )
    head, _ = await wakeful.answer(missing)
    assert head["status"] == 404  # containers the agent did not create stay invisible


async def test_a_token_sent_by_wakeful_is_ignored(
    wakeful: FakeWakeful, running: tuple[Tunnel, ServerConnection]
) -> None:
    _, ws = running
    call = await wakeful.call(
        ws, target="agent", path="/host", headers=[["authorization", "Bearer something-else"]]
    )
    head, _ = await wakeful.answer(call)
    assert head["status"] == 200  # the agent uses its own, never what arrives


# ---------------------------------------------------------------- relaying to vLLM


async def test_a_call_for_one_of_its_containers_is_relayed(
    wakeful: FakeWakeful,
    running: tuple[Tunnel, ServerConnection],
    stand_in: tuple[StandIn, int],
) -> None:
    thing, port = stand_in
    _, ws = running
    call = await wakeful.call(
        ws,
        target="vllm",
        port=port,
        path="/echo?x=1",
        method="POST",
        body=b'{"hello": "world"}',
        headers=[["authorization", "Bearer vllm-key"], ["content-type", "application/json"]],
    )
    head, body = await wakeful.answer(call)
    assert head["status"] == 200
    assert json.loads(body) == {"echo": '{"hello": "world"}'}
    method, path, headers, sent = thing.hits[-1]
    assert (method, path, sent) == ("POST", "/echo", b'{"hello": "world"}')
    assert headers["authorization"] == "Bearer vllm-key"  # vLLM's own key passes through


async def test_other_ports_are_refused_and_never_called(
    wakeful: FakeWakeful,
    running: tuple[Tunnel, ServerConnection],
    stand_in: tuple[StandIn, int],
) -> None:
    thing, port = stand_in
    _, ws = running
    other = await wakeful.call(ws, target="vllm", port=22, path="/echo")
    frame = await wakeful.frame(other)
    assert frame["t"] == "error"
    assert "not one of this agent's containers" in frame["message"]
    assert not thing.hits
    nothing = await wakeful.call(ws, target="vllm", port=None, path="/echo")
    assert (await wakeful.frame(nothing))["t"] == "error"
    del port


async def test_a_port_listed_in_the_settings_is_allowed(
    wakeful: FakeWakeful,
    cache_root: Path,
    docker: FakeDocker,
    stand_in: tuple[StandIn, int],
) -> None:
    thing, port = stand_in
    settings = make_settings(wakeful, cache_root, relay_ports=str(port))
    tunnel = Tunnel(settings, create_app(settings, docker, FakeHost()), docker)
    task = asyncio.create_task(tunnel.run())
    ws = await asyncio.wait_for(wakeful.connections.get(), 5)
    call = await wakeful.call(ws, target="vllm", port=port, path="/echo")
    head, _ = await wakeful.answer(call)
    assert head["status"] == 200
    assert thing.hits
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_big_answers_are_cut_into_bounded_frames(
    wakeful: FakeWakeful,
    running: tuple[Tunnel, ServerConnection],
    stand_in: tuple[StandIn, int],
) -> None:
    _, port = stand_in
    _, ws = running
    call = await wakeful.call(ws, target="vllm", port=port, path="/big")
    assert (await wakeful.frame(call))["t"] == "head"
    total, largest = 0, 0
    while True:
        frame = await wakeful.frame(call)
        if frame["t"] == "end":
            break
        size = len(base64.b64decode(frame["b"]))
        total, largest = total + size, max(largest, size)
    assert total == CHUNK_BYTES * 2 + 5
    assert largest <= CHUNK_BYTES


async def test_streams_arrive_as_they_are_produced_and_stop_when_cancelled(
    wakeful: FakeWakeful,
    running: tuple[Tunnel, ServerConnection],
    stand_in: tuple[StandIn, int],
) -> None:
    thing, port = stand_in
    _, ws = running
    call = await wakeful.call(ws, target="vllm", port=port, path="/slow")
    assert (await wakeful.frame(call))["t"] == "head"
    first = await wakeful.frame(call)
    second = await wakeful.frame(call)
    assert base64.b64decode(first["b"]) == b"data: 0\n\n"  # before the stream has finished
    assert base64.b64decode(second["b"]) == b"data: 1\n\n"
    await ws.send(json.dumps({"t": "cancel", "id": call}))
    await asyncio.wait_for(thing.stream_dropped.wait(), 5)  # vLLM saw the caller go


async def test_losing_the_connection_stops_running_calls(
    wakeful: FakeWakeful,
    running: tuple[Tunnel, ServerConnection],
    stand_in: tuple[StandIn, int],
) -> None:
    thing, port = stand_in
    _, ws = running
    await wakeful.call(ws, target="vllm", port=port, path="/slow")
    await asyncio.wait_for(thing.stream_started.wait(), 5)
    await ws.close()
    await asyncio.wait_for(thing.stream_dropped.wait(), 5)


async def test_an_unreachable_container_is_reported_not_crashed_on(
    wakeful: FakeWakeful,
    running: tuple[Tunnel, ServerConnection],
    docker: FakeDocker,
    cache_root: Path,
) -> None:
    _, ws = running
    docker.containers["vllm-a"] = docker.containers["vllm-a"].model_copy(update={"port": 1})
    call = await wakeful.call(ws, target="vllm", port=1, path="/echo")
    frame = await wakeful.frame(call)
    assert frame["t"] == "error"
    assert "ConnectError" in frame["message"]
    again = await wakeful.call(ws, target="agent", path="/healthz")
    assert (await wakeful.answer(again))[0]["status"] == 200  # still serving


async def test_an_unknown_target_is_an_error(
    wakeful: FakeWakeful, running: tuple[Tunnel, ServerConnection]
) -> None:
    _, ws = running
    call = await wakeful.call(ws, target="shell", path="/")
    assert (await wakeful.frame(call))["t"] == "error"


# ---------------------------------------------------------------- settings


def test_connecting_out_needs_a_secure_address_and_a_token(cache_root: Path) -> None:
    good = "wss://wakeful.example.com/api/agent/connect"

    def build(url: str, token: str) -> Settings:
        return Settings(connect_url=url, connect_token=token, cache_roots=[cache_root])

    assert build(good, CONNECT_TOKEN).connect_url
    with pytest.raises(ValidationError, match="wss://"):
        build("ws://wakeful.example.com/x", CONNECT_TOKEN)
    with pytest.raises(ValidationError, match="AGENT_CONNECT_TOKEN"):
        build(good, "short")
    assert build("ws://127.0.0.1:8000/api/agent/connect", CONNECT_TOKEN).connect_url


def test_without_a_token_nobody_can_call_in_over_http(cache_root: Path) -> None:
    settings = Settings(
        connect_url="wss://w.example.com/api/agent/connect",
        connect_token=CONNECT_TOKEN,
        cache_roots=[cache_root],
    )
    assert len(settings.token) >= 32  # random, unknown to anyone
    with pytest.raises(ValidationError, match="AGENT_TOKEN"):
        Settings(cache_roots=[cache_root])
    with pytest.raises(ValidationError, match="at least"):
        Settings(token="short", cache_roots=[cache_root])
