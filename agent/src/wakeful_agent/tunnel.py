"""The outbound connection: the agent dials Wakeful and Wakeful sends its calls down it.

A server behind a firewall cannot be called, but it can call out. The agent keeps one WebSocket open
to Wakeful (``AGENT_CONNECT_URL``) and answers what arrives on it, so the server needs no open port,
no TLS certificate and no web-server rule.

Two kinds of calls arrive (the protocol is described in ``PROTOCOL.md``):

* ``agent``: the agent's own endpoints (containers, host, logs). They are answered by the agent's
  own application, in this process, exactly as if they had come over HTTP.
* ``vllm``: a call for a vLLM container on this machine, relayed to ``127.0.0.1:<port>`` and
  streamed back. Only ports of containers this agent manages (or listed in ``AGENT_RELAY_PORTS``)
  are reachable, so the connection cannot be used to reach anything else on the machine.
"""

import asyncio
import base64
import contextlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
import websockets
from fastapi import FastAPI
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import ConnectionClosed, InvalidStatus, WebSocketException

from wakeful_agent import __version__
from wakeful_agent.docker import Docker
from wakeful_agent.settings import Settings

log = logging.getLogger(__name__)

CHUNK_BYTES = 256 * 1024  # one data frame never carries more than this
MAX_FRAME_BYTES = 4 * 1024 * 1024  # larger than any frame either side sends
_PING_S = 20.0
_PING_TIMEOUT_S = 30.0
_OPEN_TIMEOUT_S = 15.0
_MIN_DELAY_S = 1.0
_MAX_DELAY_S = 30.0
_REFUSED_DELAY_S = 30.0
_PORT_CACHE_S = 10.0
_FORBIDDEN = 403
_BAD_GATEWAY = 502
_REPLACED = 4000  # Wakeful's close code when another connection took this server's place

# Headers that describe one hop, not the message: never copied across.
_HOP = frozenset({"connection", "keep-alive", "transfer-encoding", "te", "upgrade", "host"})
_NOT_FORWARDED_REQUEST = _HOP | {"content-length"}


@dataclass
class _Call:
    """A request that is still arriving (head first, then body frames, then ``end``)."""

    id: int
    target: str
    port: int | None
    method: str
    path: str
    headers: list[tuple[str, str]]
    body: bytearray = field(default_factory=bytearray)


class Tunnel:
    """Keeps the connection to Wakeful up and answers what comes through it."""

    def __init__(self, settings: Settings, app: FastAPI, docker: Docker) -> None:
        self._settings = settings
        self._docker = docker
        self._local = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://agent",
            timeout=httpx.Timeout(None),
        )
        self._vllm = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None))
        self._ports: set[int] = set(settings.relay_ports)
        self._ports_at = 0.0
        self._ws: ClientConnection | None = None
        self._arriving: dict[int, _Call] = {}
        self._running: dict[int, asyncio.Task[None]] = {}
        self.connected = asyncio.Event()

    # ---------------------------------------------------------------- connection

    async def run(self) -> None:
        """Connect, serve, and reconnect forever (until cancelled)."""
        url = self._settings.connect_url
        if not url:
            return
        delay = _MIN_DELAY_S
        try:
            while True:
                refused = False
                try:
                    async with websockets.connect(
                        url,
                        additional_headers={
                            "Authorization": f"Bearer {self._settings.connect_token}"
                        },
                        max_size=MAX_FRAME_BYTES,
                        ping_interval=_PING_S,
                        ping_timeout=_PING_TIMEOUT_S,
                        open_timeout=_OPEN_TIMEOUT_S,
                    ) as ws:
                        delay = _MIN_DELAY_S
                        await self._serve(ws)
                except InvalidStatus as error:
                    refused = True
                    log.error(  # noqa: TRY400 - an expected condition, no traceback wanted
                        "Wakeful refused the connection (HTTP %s): is the token right, and was it "
                        "revoked?",
                        error.response.status_code,
                    )
                except (OSError, TimeoutError, WebSocketException) as error:
                    log.warning("connection to Wakeful lost: %s", error or type(error).__name__)
                wait = _REFUSED_DELAY_S if refused else delay
                await asyncio.sleep(wait * random.uniform(0.8, 1.2))  # noqa: S311 - jitter only
                delay = min(delay * 2, _MAX_DELAY_S)
        finally:
            await self._local.aclose()
            await self._vllm.aclose()

    async def _serve(self, ws: ClientConnection) -> None:
        self._ws = ws
        self.connected.set()
        log.info("connected to Wakeful")
        try:
            await self._send({"t": "hello", "version": __version__})
            async for raw in ws:
                try:
                    message = json.loads(raw)
                    self._receive(message)
                except (ValueError, KeyError, TypeError):
                    log.warning("ignored a malformed message from Wakeful")
        except ConnectionClosed as closed:
            if closed.rcvd is not None and closed.rcvd.code == _REPLACED:
                log.warning(
                    "another agent connected with this token and took over: is the agent running "
                    "twice?"
                )
        finally:
            self.connected.clear()
            self._ws = None
            self._arriving.clear()
            for task in list(self._running.values()):
                task.cancel()
            await asyncio.gather(*self._running.values(), return_exceptions=True)
            self._running.clear()

    async def _send(self, message: dict[str, Any]) -> None:
        ws = self._ws
        if ws is None:
            return
        with contextlib.suppress(ConnectionClosed):
            await ws.send(json.dumps(message, separators=(",", ":")))

    # ---------------------------------------------------------------- incoming frames

    def _receive(self, message: dict[str, Any]) -> None:
        kind = message["t"]
        call_id = int(message["id"]) if "id" in message else -1
        if kind == "req":
            self._arriving[call_id] = _Call(
                id=call_id,
                target=str(message["target"]),
                port=int(message["port"]) if message.get("port") is not None else None,
                method=str(message["method"]),
                path=str(message["path"]),
                headers=[(str(k), str(v)) for k, v in message["headers"]],
            )
        elif kind == "data":
            if call := self._arriving.get(call_id):
                call.body += base64.b64decode(message["b"])
        elif kind == "end":
            if call := self._arriving.pop(call_id, None):
                self._running[call_id] = asyncio.create_task(self._answer(call))
        elif kind == "cancel":
            self._arriving.pop(call_id, None)
            if task := self._running.get(call_id):
                task.cancel()

    # ---------------------------------------------------------------- answering

    async def _answer(self, call: _Call) -> None:
        try:
            if call.target == "agent":
                answered = await self._answer_locally(call)
            elif call.target == "vllm":
                answered = await self._answer_from_vllm(call)
            else:
                await self._send(
                    {"t": "error", "id": call.id, "message": f"unknown target '{call.target}'"}
                )
                return
            if answered:
                await self._send({"t": "end", "id": call.id})
        except asyncio.CancelledError:
            raise  # Wakeful gave up on this call (or the connection went); nothing to answer
        except httpx.HTTPError as error:
            await self._send(
                {
                    "t": "error",
                    "id": call.id,
                    "message": f"{type(error).__name__}: {error}".strip(": "),
                }
            )
        except Exception as error:
            log.exception("call %s %s failed", call.method, call.path)
            await self._send({"t": "error", "id": call.id, "message": f"agent error: {error}"})
        finally:
            self._running.pop(call.id, None)

    def _request_headers(self, call: _Call) -> list[tuple[str, str]]:
        return [(k, v) for k, v in call.headers if k.lower() not in _NOT_FORWARDED_REQUEST]

    async def _answer_locally(self, call: _Call) -> bool:
        """Run one of the agent's own endpoints through its own application; True once answered."""
        headers = [(k, v) for k, v in self._request_headers(call) if k.lower() != "authorization"]
        headers.append(("Authorization", f"Bearer {self._settings.token}"))
        response = await self._local.request(
            call.method, call.path, headers=headers, content=bytes(call.body)
        )
        await self._send_head(call.id, response)
        await self._send_body(call.id, response.content)
        return True

    async def _answer_from_vllm(self, call: _Call) -> bool:
        """Relay a call to a local vLLM container and stream its answer; False if it was refused."""
        port = call.port
        if port is None or not await self._port_allowed(port):
            await self._send(
                {
                    "t": "error",
                    "id": call.id,
                    "message": f"port {port} is not one of this agent's containers: create the "
                    "container with Wakeful, or list the port in AGENT_RELAY_PORTS",
                }
            )
            return False
        request = self._vllm.build_request(
            call.method,
            f"http://127.0.0.1:{port}{call.path}",
            headers=self._request_headers(call),
            content=bytes(call.body),
        )
        upstream = await self._vllm.send(request, stream=True)
        try:
            await self._send_head(call.id, upstream)
            async for chunk in upstream.aiter_raw():
                await self._send_body(call.id, chunk)
        finally:
            await upstream.aclose()  # also when cancelled, so vLLM drops the request
        return True

    async def _send_head(self, call_id: int, response: httpx.Response) -> None:
        headers = [(k, v) for k, v in response.headers.multi_items() if k.lower() not in _HOP]
        await self._send(
            {"t": "head", "id": call_id, "status": response.status_code, "headers": headers}
        )

    async def _send_body(self, call_id: int, data: bytes) -> None:
        for start in range(0, len(data), CHUNK_BYTES):
            piece = data[start : start + CHUNK_BYTES]
            await self._send({"t": "data", "id": call_id, "b": base64.b64encode(piece).decode()})

    async def _port_allowed(self, port: int) -> bool:
        if port in self._settings.relay_ports:
            return True
        if port in self._ports and time.monotonic() - self._ports_at < _PORT_CACHE_S:
            return True
        self._ports = {c.port for c in await self._docker.list() if c.port is not None}
        self._ports_at = time.monotonic()
        return port in self._ports
