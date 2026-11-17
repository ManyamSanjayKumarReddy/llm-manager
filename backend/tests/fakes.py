"""Fake vLLM containers that police the rules the engine must obey."""

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

USAGE = {"prompt_tokens": 7, "completion_tokens": 5, "total_tokens": 12}  # what every fake reports


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
        self.ghost_until = (
            0.0  # like vLLM: an aborted request still occupies the engine for a moment
        )
        self.metrics_enabled = True
        # "live": counters move while busy; "frozen": vLLM keeps no stats; "missing": no counters
        self.counters = "live"
        self.fail_is_sleeping = 0  # the next N /is_sleeping calls fail
        self.version = "0.10.1"  # from 0.17 on, /sleep aborts running requests itself
        self.tokens = 0
        self.abort_lag_s = 0.0  # a cancelled request keeps the engine busy this long (see sleep)
        self.api_key: str | None = (
            None  # like `vllm serve --api-key`: protects everything but /health
        )
        self.last_model: str | None = None
        self.last_body: dict[str, Any] = {}
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
            numbers = tuple(int(x) for x in self.version.split("+")[0].split(".")[:2])
            if numbers >= (0, 17) or "abortsleep" in self.version:
                self.ghost_until = 0.0  # the engine drops whatever it still held
            if self.active:
                self.ledger.violations.append(f"{self.name} slept with {self.active} in flight")
            if time.monotonic() < self.ghost_until:
                self.ledger.violations.append(
                    f"{self.name} slept while its engine was still running"
                )
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

        @app.get("/version")
        async def version() -> dict[str, str]:
            return {"version": self.version}

        @app.get("/health")
        async def health() -> JSONResponse:
            return JSONResponse({})

        @app.get("/v1/models")
        async def models() -> dict[str, Any]:
            return {"data": [{"id": f"org/{self.name}"}]}

        @app.get("/metrics")
        async def metrics() -> Response:
            if not self.metrics_enabled:
                return JSONResponse({"error": "not found"}, status_code=404)
            busy = self.active > 0 or time.monotonic() < self.ghost_until
            if busy and self.counters == "live":
                self.tokens += 10  # the engine is working: its token counters move
            labels = f'{{engine="0",model_name="org/{self.name}"}}'
            # Like the real thing, the "running" gauge keeps its last value or stays 0: no use.
            text = f"vllm:num_requests_running{labels} 0.0\n"
            if self.counters != "missing":
                text += f"vllm:generation_tokens_total{labels} {self.tokens}.0\n"
                text += f"vllm:prompt_tokens_total{labels} 5.0\n"
                text += f"vllm:generation_tokens_created{labels} 1.7e9\n"
            return Response(text, media_type="text/plain")

        @app.get("/is_sleeping", response_model=None)
        async def is_sleeping() -> Response | dict[str, bool]:
            if self.fail_is_sleeping > 0:  # a loaded server that misses an answer
                self.fail_is_sleeping -= 1
                return JSONResponse({"error": "busy"}, status_code=503)
            return {"is_sleeping": self.sleeping}

        @app.post("/v1/chat/completions", response_model=None)
        async def chat(request: Request) -> Response | dict[str, Any]:
            body = await request.json()
            self.last_model = body.get("model")
            self.last_body = body
            if self.sleeping:
                self.ledger.violations.append(f"{self.name} got a request while asleep")
                return JSONResponse({"error": "asleep"}, status_code=500)
            self.active += 1
            try:
                await asyncio.sleep(body.get("work_s", self.work_s))
            except asyncio.CancelledError:
                self.ghost_until = max(self.ghost_until, time.monotonic() + self.abort_lag_s)
                raise
            finally:
                self.active -= 1
            self.served += 1
            if body.get("fail"):
                return JSONResponse({"error": "model error"}, status_code=500)
            if body.get("stream"):

                async def chunks() -> AsyncIterator[bytes]:
                    for i in range(3):
                        yield f"data: chunk{i}\n\n".encode()
                    if (body.get("stream_options") or {}).get("include_usage"):
                        # like vLLM: a last chunk with no choices that carries the totals
                        tail = f'"choices": [], "usage": {json.dumps(USAGE)}'
                        yield f'data: {{"id": "x", {tail}}}\n\n'.encode()
                    yield b"data: [DONE]\n\n"

                return StreamingResponse(chunks(), media_type="text/event-stream")
            return {"id": "x", "model": self.last_model, "served_by": self.name, "usage": USAGE}

        return app


class Dispatch(httpx.AsyncBaseTransport):
    """Routes ``http://127.0.0.1:<port>`` to the fake container that owns that port.

    Ports in ``down`` (and ports nobody owns) refuse the connection, like a stopped container.
    """

    def __init__(self, apps_by_port: dict[int, FastAPI]) -> None:
        self._transports = {p: httpx.ASGITransport(app=a) for p, a in apps_by_port.items()}
        self._hosts: dict[str, httpx.ASGITransport] = {}
        self.down: set[int] = set()

    def add_host(self, host: str, app: FastAPI) -> None:
        """Serve ``https://<host>/...`` from ``app`` (a fake agent)."""
        self._hosts[host] = httpx.ASGITransport(app=app)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.host in self._hosts:
            return await self._hosts[request.url.host].handle_async_request(request)
        port = request.url.port
        if port is None or port in self.down or port not in self._transports:
            raise httpx.ConnectError("connection refused", request=request)
        return await self._transports[port].handle_async_request(request)


class FakeAgent:
    """A Wakeful agent for one server: keeps containers in memory and drives the fake vLLMs.

    Stopping a container makes its port refuse connections; starting or restarting it brings
    back a *fresh* (awake) container, like the real thing.
    """

    def __init__(
        self,
        dispatch: "Dispatch",
        ledger: Ledger,
        fakes: dict[str, FakeVLLM],
        ports: dict[str, int],
        token: str,
    ) -> None:
        self.dispatch, self.ledger, self.fakes, self.ports, self.token = (
            dispatch,
            ledger,
            fakes,
            ports,
            token,
        )
        self.containers: dict[str, dict[str, Any]] = {}
        self.created: list[dict[str, Any]] = []
        self.calls: list[tuple[str, str]] = []
        self.app = self._build()

    def seed(self, name: str, port: int, gpus: list[int]) -> None:
        """A container that already exists (running)."""
        self.containers[name] = self._record(name, port, gpus, running=True)

    @staticmethod
    def _record(name: str, port: int, gpus: list[int], *, running: bool) -> dict[str, Any]:
        return {
            "name": name,
            "state": "running" if running else "exited",
            "running": running,
            "status": "Up 3 hours" if running else "Exited (0) 1 minute ago",
            "image": "vllm/vllm-openai:v0.10.1",
            "port": port,
            "gpus": gpus,
            "model": "org/model",
            "restart_policy": "unless-stopped",
            "exit_code": None if running else 0,
            "oom_killed": False,
            "created_at": "2026-11-17T00:00:00Z",
            "started_at": "2026-11-17T00:00:01Z" if running else None,
        }

    def _fake_on(self, port: int) -> FakeVLLM | None:
        for name, p in self.ports.items():
            if p == port:
                return self.fakes.get(name)
        return None

    def _set_running(self, name: str, *, running: bool, fresh: bool = False) -> dict[str, Any]:
        container = self.containers[name]
        container.update(
            running=running,
            state="running" if running else "exited",
            exit_code=None if running else 0,
        )
        port, fake = container["port"], self._fake_on(container["port"])
        if not running:
            self.dispatch.down.add(port)
            if fake is not None:
                self.ledger.sleep(fake.name)
        else:
            self.dispatch.down.discard(port)
            if fake is not None and fresh:
                fake.sleeping = False  # a restarted vLLM starts awake
                self.ledger.awake.add(fake.name)
        return container

    def _build(self) -> FastAPI:
        app = FastAPI()

        @app.middleware("http")
        async def require_token(request: Request, call_next: Any) -> Response:
            if request.headers.get("authorization") != f"Bearer {self.token}":
                return JSONResponse({"detail": "wrong or missing token"}, status_code=401)
            response: Response = await call_next(request)
            return response

        def get(name: str) -> dict[str, Any]:
            if name not in self.containers:
                raise HTTPException(404, f"no container called '{name}' is managed by this agent")
            return self.containers[name]

        @app.get("/host")
        async def host() -> dict[str, Any]:
            return {
                "gpus": [
                    {
                        "index": 0,
                        "name": "Fake GPU",
                        "memory_used_mb": 1000,
                        "memory_total_mb": 16000,
                        "utilization_pct": 4,
                        "temperature_c": 40,
                    }
                ],
                "gpu_error": None,
                "ram_total_mb": 64000,
                "ram_available_mb": 20000,
                "swap_total_mb": 26000,
                "swap_used_mb": 11000,
                "disk_total_gb": 900.0,
                "disk_free_gb": 400.0,
                "disk_path": "/root/.cache",
                "cpu_count": 16,
                "load_1m": 0.5,
            }

        @app.get("/containers")
        async def list_containers() -> list[dict[str, Any]]:
            return sorted(self.containers.values(), key=lambda c: c["name"])

        @app.post("/containers", status_code=201)
        async def create(request: Request) -> dict[str, Any]:
            body = await request.json()
            if body["name"] in self.containers:
                raise HTTPException(409, f"a container called '{body['name']}' already exists")
            if body["image"].startswith("evil/"):
                raise HTTPException(422, "image: only these repositories are allowed here")
            self.created.append(body)
            self.containers[body["name"]] = self._record(
                body["name"], body["port"], sorted(body["gpus"]), running=True
            )
            return self.containers[body["name"]]

        @app.get("/containers/{name}")
        async def one(name: str) -> dict[str, Any]:
            return get(name)

        @app.post("/containers/{name}/{verb}")
        async def act(name: str, verb: str) -> dict[str, Any]:
            get(name)
            self.calls.append((verb, name))
            if verb == "stop":
                return self._set_running(name, running=False)
            return self._set_running(name, running=True, fresh=verb in {"start", "restart"})

        @app.delete("/containers/{name}", status_code=204)
        async def remove(name: str) -> Response:
            get(name)
            self.calls.append(("remove", name))
            self._set_running(name, running=False)
            del self.containers[name]
            return Response(status_code=204)

        @app.get("/containers/{name}/logs")
        async def logs(name: str, tail: int = 200) -> dict[str, Any]:
            get(name)
            return {"name": name, "text": f"last {tail} lines\n", "truncated": False}

        return app
