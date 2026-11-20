"""A GPU server's agent that dials Wakeful, written from the protocol description only.

It speaks the wire format of ``agent/PROTOCOL.md`` over a real WebSocket, so the backend's side is
tested without the real agent. Calls are answered by in-process fake vLLM containers / a fake agent.
"""

import asyncio
import base64
import contextlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import uvicorn
import websockets
from fastapi import FastAPI
from websockets.asyncio.client import ClientConnection


class ServedApp:
    """The application served on a real local port (uvicorn), so WebSockets can connect."""

    def __init__(self, app: FastAPI) -> None:
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
        )
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> int:
        self._task = asyncio.create_task(self._server.serve())
        while not self._server.started:  # noqa: ASYNC110 - uvicorn offers no event to wait on
            await asyncio.sleep(0.01)
        return int(self._server.servers[0].sockets[0].getsockname()[1])

    async def stop(self) -> None:
        self._server.should_exit = True
        if self._task is not None:
            await self._task


class FakeTunnelAgent:
    """Connects out, then answers calls for the vLLM ports and agent endpoints it was given."""

    def __init__(
        self,
        url: str,
        token: str,
        vllm: dict[int, FastAPI],
        agent_app: FastAPI | None = None,
        agent_token: str = "",
        version: str = "0.1.0",
    ) -> None:
        self.url, self.token, self.version = url, token, version
        self.vllm = {p: httpx.ASGITransport(app=a) for p, a in vllm.items()}
        self.agent = httpx.ASGITransport(app=agent_app) if agent_app else None
        self.agent_token = agent_token
        self.received: list[dict[str, Any]] = []  # every frame the backend sent
        self.cancelled: list[int] = []
        self.close_code: int | None = None
        self.hello_delay_s = 0.0
        self._ws: ClientConnection | None = None
        self._calls: dict[int, dict[str, Any]] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._reader: asyncio.Task[None] | None = None
        self.connected = asyncio.Event()

    async def start(self) -> None:
        self._ws = await websockets.connect(
            self.url, additional_headers={"Authorization": f"Bearer {self.token}"}
        )
        self._reader = asyncio.create_task(self._read())
        await asyncio.sleep(self.hello_delay_s)
        await self._send({"t": "hello", "version": self.version})
        self.connected.set()

    async def stop(self) -> None:
        if self._ws is not None:
            await self._ws.close()
        if self._reader is not None:
            await asyncio.gather(self._reader, return_exceptions=True)

    async def wait_closed(self) -> None:
        assert self._reader is not None
        await asyncio.wait_for(self._reader, 5)

    async def _send(self, message: dict[str, Any]) -> None:
        assert self._ws is not None
        with contextlib.suppress(websockets.ConnectionClosed):
            await self._ws.send(json.dumps(message))

    async def _read(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                frame = json.loads(raw)
                self.received.append(frame)
                call_id = frame.get("id")
                if frame["t"] == "req":
                    self._calls[call_id] = {**frame, "body": b""}
                elif frame["t"] == "data":
                    self._calls[call_id]["body"] += base64.b64decode(frame["b"])
                elif frame["t"] == "end":
                    self._tasks[call_id] = asyncio.create_task(
                        self._answer(self._calls.pop(call_id))
                    )
                elif frame["t"] == "cancel":
                    self.cancelled.append(call_id)
                    if task := self._tasks.get(call_id):
                        task.cancel()
        except websockets.ConnectionClosed:
            pass
        finally:
            if self._ws.close_code is not None:
                self.close_code = self._ws.close_code
            for task in self._tasks.values():
                task.cancel()

    async def _answer(self, call: dict[str, Any]) -> None:
        headers = [
            (k, v) for k, v in call["headers"] if k.lower() not in {"host", "content-length"}
        ]
        if call["target"] == "agent":
            transport = self.agent
            headers = [(k, v) for k, v in headers if k.lower() != "authorization"]
            headers.append(("Authorization", f"Bearer {self.agent_token}"))
            base = "http://agent"
        else:
            transport = self.vllm.get(call["port"])
            base = f"http://127.0.0.1:{call['port']}"
        if transport is None:
            await self._send({"t": "error", "id": call["id"], "message": "no such port"})
            return
        async with httpx.AsyncClient(
            transport=transport, base_url=base, timeout=httpx.Timeout(None)
        ) as client:
            response = await client.request(
                call["method"], call["path"], headers=headers, content=call["body"]
            )
        await self._send(
            {
                "t": "head",
                "id": call["id"],
                "status": response.status_code,
                "headers": [
                    [k, v]
                    for k, v in response.headers.multi_items()
                    if k.lower() not in {"transfer-encoding", "connection"}
                ],
            }
        )
        body = response.content
        for start in range(0, len(body), 64):  # small frames, to exercise reassembly
            piece = base64.b64encode(body[start : start + 64]).decode()
            await self._send({"t": "data", "id": call["id"], "b": piece})
        await self._send({"t": "end", "id": call["id"]})


Waiter = Callable[[], Awaitable[bool]]
