"""Servers that connect out: the hub that holds their connections, and the transport that uses them.

A server behind a firewall cannot be called, so its agent dials Wakeful and keeps a WebSocket open
(``/api/agent/connect``). Everything meant for that server then travels down that connection:
calls to the agent, health and sleep calls to vLLM, and the users' requests (streamed back).

``TunnelRouter`` is the one place that knows about this. It is the transport of the shared HTTP
client, so the rest of the code keeps calling ``client.request(...)`` as before: a call that names a
tunnelled server (``extensions={"wakeful.server": name}``) goes down that server's connection, every
other call goes out normally. The wire format is described in ``agent/PROTOCOL.md``.
"""

import asyncio
import base64
import contextlib
import itertools
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import WebSocket
from starlette.websockets import WebSocketDisconnect

from llm_manager.core.routing import SERVER_KEY, TARGET_KEY

log = logging.getLogger(__name__)

CHUNK_BYTES = 256 * 1024
REPLACED = 4000  # close code sent to a connection that another one took the place of
_DEFAULT_HTTP_PORT = 80
_LOST = {"t": "lost"}


@dataclass(frozen=True)
class TunnelInfo:
    """What the dashboard shows about a server's connection."""

    connected: bool
    agent_version: str | None
    connected_since: float | None


class _Connection:
    """One agent's WebSocket and the calls waiting for an answer on it."""

    def __init__(self, server: str, ws: WebSocket) -> None:
        self.server = server
        self.ws = ws
        self.pending: dict[int, asyncio.Queue[dict[str, Any]]] = {}
        self.ids = itertools.count(1)
        self.agent_version: str | None = None
        self.since = time.time()
        self._send_lock = asyncio.Lock()

    async def send(self, message: dict[str, Any]) -> None:
        """Send one frame (raises ``ConnectionError`` if the connection is gone)."""
        try:
            async with self._send_lock:
                await self.ws.send_text(json.dumps(message, separators=(",", ":")))
        except (WebSocketDisconnect, RuntimeError, OSError) as error:
            raise ConnectionError("the connection to the agent is closed") from error

    async def cancel(self, call_id: int) -> None:
        """Tell the agent to stop working on a call (best effort), and forget it."""
        self.pending.pop(call_id, None)
        with contextlib.suppress(ConnectionError):  # gone: the agent stopped already
            await self.send({"t": "cancel", "id": call_id})


class _Answer(httpx.AsyncByteStream):
    """The body of an answer, read from frames as the agent produces them."""

    def __init__(
        self,
        conn: _Connection,
        call_id: int,
        queue: asyncio.Queue[dict[str, Any]],
        read_s: float | None,
    ) -> None:
        self._conn = conn
        self._id = call_id
        self._queue = queue
        self._read_s = read_s
        self._finished = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            try:
                frame = await asyncio.wait_for(self._queue.get(), self._read_s)
            except TimeoutError as error:
                raise httpx.ReadTimeout("the agent sent nothing in time") from error
            kind = frame["t"]
            if kind == "data":
                yield base64.b64decode(frame["b"])
            elif kind == "end":
                self._finished = True
                self._conn.pending.pop(self._id, None)
                return
            else:  # "error" or the connection was lost
                self._finished = True
                self._conn.pending.pop(self._id, None)
                raise httpx.ReadError(
                    str(frame.get("message") or "the connection to the agent was lost")
                )

    async def aclose(self) -> None:
        """Stop the call on the agent if the caller gave up before the end."""
        if not self._finished:
            self._finished = True
            await self._conn.cancel(self._id)


class Hub:
    """The agents that are connected right now, and the servers that are meant to be."""

    def __init__(self) -> None:
        self._tunneled: set[str] = set()
        self._conns: dict[str, _Connection] = {}
        self.on_connected: Callable[[str], None] | None = None

    # ---------------------------------------------------------------- which servers connect out

    def set_tunneled(self, names: set[str]) -> None:
        """Replace the set of servers that are reached through their agent's connection."""
        self._tunneled = set(names)

    def is_tunneled(self, name: str) -> bool:
        """Is this server reached through a connection (rather than by address)?"""
        return name in self._tunneled

    async def enable(self, name: str) -> None:
        """Start reaching ``name`` through its connection (and drop one made with an old token)."""
        self._tunneled.add(name)
        await self.disconnect(name)

    async def disable(self, name: str) -> None:
        """Stop reaching ``name`` through a connection, and close it."""
        self._tunneled.discard(name)
        await self.disconnect(name)

    async def disconnect(self, name: str) -> None:
        """Close the server's connection, if any (the agent will try again with its token)."""
        conn = self._conns.get(name)
        if conn is not None:
            with contextlib.suppress(RuntimeError, OSError):
                await conn.ws.close(code=1008)

    # ---------------------------------------------------------------- state

    def info(self, name: str) -> TunnelInfo:
        """Whether the server's agent is connected."""
        conn = self._conns.get(name)
        if conn is None:
            return TunnelInfo(connected=False, agent_version=None, connected_since=None)
        return TunnelInfo(
            connected=True, agent_version=conn.agent_version, connected_since=conn.since
        )

    # ---------------------------------------------------------------- the connection itself

    async def serve(self, name: str, ws: WebSocket) -> None:
        """Hold an agent's connection open and route its answers, until it closes."""
        await ws.accept()
        conn = _Connection(name, ws)
        old = self._conns.get(name)
        self._conns[name] = conn
        if old is not None:
            log.warning("a second agent connected for %s: closing the first", name)
            with contextlib.suppress(RuntimeError, OSError):
                await old.ws.close(code=REPLACED)
        log.info("agent connected for server %s", name)
        try:
            while True:
                text = await ws.receive_text()
                try:
                    self._route(conn, json.loads(text))
                except (ValueError, KeyError, TypeError):
                    log.warning("ignored a malformed frame from the agent on %s", name)
        except WebSocketDisconnect:
            pass
        except RuntimeError:
            pass  # the socket closed while receiving
        finally:
            if self._conns.get(name) is conn:
                del self._conns[name]
            for queue in conn.pending.values():
                queue.put_nowait(_LOST)
            log.info("agent disconnected for server %s", name)

    def _route(self, conn: _Connection, frame: dict[str, Any]) -> None:
        kind = frame["t"]
        if kind == "hello":
            conn.agent_version = str(frame.get("version"))
            if self.on_connected is not None:
                self.on_connected(conn.server)
            return
        queue = conn.pending.get(int(frame["id"]))
        if queue is not None:  # unknown ids are calls that were cancelled meanwhile
            queue.put_nowait(frame)

    # ---------------------------------------------------------------- calls

    async def request(self, name: str, request: httpx.Request) -> httpx.Response:
        """Send one HTTP call down the server's connection and return the (streaming) answer."""
        conn = self._conns.get(name)
        if conn is None:
            raise httpx.ConnectError(f"the agent on {name} is not connected", request=request)
        target = str(request.extensions.get(TARGET_KEY, "vllm"))
        timeout: dict[str, float | None] = request.extensions.get("timeout", {})
        read_s = timeout.get("read")
        body = await request.aread()
        call_id = next(conn.ids)
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        conn.pending[call_id] = queue
        try:
            await conn.send(
                {
                    "t": "req",
                    "id": call_id,
                    "target": target,
                    "port": (request.url.port or _DEFAULT_HTTP_PORT) if target == "vllm" else None,
                    "method": request.method,
                    "path": request.url.raw_path.decode("ascii"),
                    "headers": [[k, v] for k, v in request.headers.multi_items()],
                }
            )
            for start in range(0, len(body), CHUNK_BYTES):
                piece = base64.b64encode(body[start : start + CHUNK_BYTES]).decode()
                await conn.send({"t": "data", "id": call_id, "b": piece})
            await conn.send({"t": "end", "id": call_id})
            head = await self._head(queue, read_s, request)
        except ConnectionError as error:
            conn.pending.pop(call_id, None)
            raise httpx.ConnectError(str(error), request=request) from error
        except BaseException:
            await conn.cancel(call_id)
            raise
        return httpx.Response(
            head["status"],
            headers=[(k, v) for k, v in head["headers"]],
            stream=_Answer(conn, call_id, queue, read_s),
            request=request,
        )

    @staticmethod
    async def _head(
        queue: asyncio.Queue[dict[str, Any]], read_s: float | None, request: httpx.Request
    ) -> dict[str, Any]:
        try:
            frame = await asyncio.wait_for(queue.get(), read_s)
        except TimeoutError as error:
            raise httpx.ReadTimeout("the agent did not answer in time", request=request) from error
        if frame["t"] == "head":
            return frame
        raise httpx.ConnectError(
            str(frame.get("message") or "the connection to the agent was lost"), request=request
        )


class TunnelRouter(httpx.AsyncBaseTransport):
    """Sends calls for tunnelled servers down their connection, everything else the normal way."""

    def __init__(self, hub: Hub, inner: httpx.AsyncBaseTransport) -> None:
        self._hub = hub
        self._inner = inner

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Route one call."""
        server = request.extensions.get(SERVER_KEY)
        if isinstance(server, str) and self._hub.is_tunneled(server):
            return await self._hub.request(server, request)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        """Close the normal transport."""
        await self._inner.aclose()
