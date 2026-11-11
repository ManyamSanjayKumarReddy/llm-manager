"""Fake vLLM containers that police the rules the engine must obey."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse


class Ledger:
    """Shared 'GPU hardware': records every rule violation."""

    def __init__(self, gpus: dict[str, frozenset[int]]) -> None:
        self.gpus = gpus
        self.awake: set[str] = set()
        self.violations: list[str] = []

    def wake(self, name: str) -> None:
        for other in self.awake:
            if self.gpus[other] & self.gpus[name]:
                self.violations.append(f"{name} woke while {other} awake on a shared GPU")
        self.awake.add(name)

    def sleep(self, name: str) -> None:
        self.awake.discard(name)


class FakeVLLM:
    """Behaves like a vLLM container with sleep mode, and records misuse."""

    def __init__(
        self,
        name: str,
        ledger: Ledger,
        *,
        work_s: float = 0.02,
        wake_s: float = 0.02,
        sleep_s: float = 0.02,
    ) -> None:
        self.name, self.ledger = name, ledger
        self.work_s, self.wake_s, self.sleep_s = work_s, wake_s, sleep_s
        self.sleeping = False
        self.active = 0
        self.served = 0
        self.fail_wake = False
        self.api_key: str | None = (
            None  # like `vllm serve --api-key`: protects everything but /health
        )
        self.last_model: str | None = None
        ledger.wake(name)  # a fresh container starts awake, like the real thing
        self.app = self._build()

    def _build(self) -> FastAPI:
        app = FastAPI()

        @app.middleware("http")
        async def require_key(request: Request, call_next: Any) -> Response:
            wrong_key = request.headers.get("authorization") != f"Bearer {self.api_key}"
            if self.api_key and request.url.path != "/health" and wrong_key:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            response: Response = await call_next(request)
            return response

        @app.post("/sleep")
        async def sleep(level: int = 1) -> JSONResponse:
            if self.active:
                self.ledger.violations.append(f"{self.name} slept with {self.active} in flight")
            await asyncio.sleep(self.sleep_s)
            self.sleeping = True
            self.ledger.sleep(self.name)
            return JSONResponse({})

        @app.post("/wake_up")
        async def wake_up() -> JSONResponse:
            if self.fail_wake:
                return JSONResponse({"error": "boom"}, status_code=500)
            await asyncio.sleep(self.wake_s)
            if self.sleeping:
                self.sleeping = False
                self.ledger.wake(self.name)
            return JSONResponse({})

        @app.get("/health")
        async def health() -> JSONResponse:
            return JSONResponse({})

        @app.get("/v1/models")
        async def models() -> dict[str, Any]:
            return {"data": [{"id": f"org/{self.name}"}]}

        @app.get("/is_sleeping")
        async def is_sleeping() -> dict[str, bool]:
            return {"is_sleeping": self.sleeping}

        @app.post("/v1/chat/completions", response_model=None)
        async def chat(request: Request) -> Response | dict[str, Any]:
            body = await request.json()
            self.last_model = body.get("model")
            if self.sleeping:
                self.ledger.violations.append(f"{self.name} got a request while asleep")
                return JSONResponse({"error": "asleep"}, status_code=500)
            self.active += 1
            try:
                await asyncio.sleep(body.get("work_s", self.work_s))
            finally:
                self.active -= 1
            self.served += 1
            if body.get("fail"):
                return JSONResponse({"error": "model error"}, status_code=500)
            if body.get("stream"):

                async def chunks() -> AsyncIterator[bytes]:
                    for i in range(3):
                        yield f"data: chunk{i}\n\n".encode()
                    yield b"data: [DONE]\n\n"

                return StreamingResponse(chunks(), media_type="text/event-stream")
            return {"id": "x", "model": self.last_model, "served_by": self.name}

        return app


class Dispatch(httpx.AsyncBaseTransport):
    """Routes ``http://127.0.0.1:<port>`` to the fake container that owns that port.

    Ports in ``down`` (and ports nobody owns) refuse the connection, like a stopped container.
    """

    def __init__(self, apps_by_port: dict[int, FastAPI]) -> None:
        self._transports = {p: httpx.ASGITransport(app=a) for p, a in apps_by_port.items()}
        self.down: set[int] = set()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        port = request.url.port
        if port is None or port in self.down or port not in self._transports:
            raise httpx.ConnectError("connection refused", request=request)
        return await self._transports[port].handle_async_request(request)
