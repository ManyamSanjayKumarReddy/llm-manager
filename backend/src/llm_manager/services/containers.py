"""Controlling the vLLM containers on a server through its agent.

The rules that keep the scheduler and the containers consistent:

* A container that backs a registered model is only stopped, restarted or removed while that
  model is quiet (no request running or waiting, not in the middle of waking or sleeping).
* After any change the scheduler looks at the container at once, so the dashboard and the next
  request see the truth.
* Removing a container that backs a model also removes the model, but only when the caller says
  so explicitly (the dashboard asks the admin to confirm).
"""

from typing import Any
from urllib.parse import urlsplit

import httpx

from llm_manager.core.errors import InvalidInputError
from llm_manager.db.models import ManagedModel, Server
from llm_manager.engine import Manager
from llm_manager.schemas.containers import ContainerCreate, ContainerOut, HostOut, LogsOut
from llm_manager.schemas.models import ModelCreate
from llm_manager.services.agents import AgentClient
from llm_manager.services.audit import AuditService
from llm_manager.services.models import ModelService
from llm_manager.services.servers import ServerService


def _url_port(url: str) -> int | None:
    try:
        return urlsplit(url).port
    except ValueError:
        return None


class ContainerService:
    """Lists, creates, changes and removes containers on servers that have an agent."""

    def __init__(
        self,
        manager: Manager,
        models: ModelService,
        audit: AuditService,
        http: httpx.AsyncClient,
    ) -> None:
        self._manager = manager
        self._models = models
        self._audit = audit
        self._http = http

    async def _agent(self, server_name: str) -> tuple[Server, AgentClient]:
        server = await ServerService.get(server_name)
        return server, AgentClient(self._http, server)

    @staticmethod
    async def _backing_model(
        server: Server, container: str, port: int | None
    ) -> ManagedModel | None:
        """The model that runs in this container: linked by name, else by an explicit URL port."""
        linked = await ManagedModel.get_or_none(server=server, container_name=container)
        if linked is not None:
            return linked
        if port is None:
            return None
        for row in await ManagedModel.filter(server=server, container_name=None):
            if _url_port(row.url) == port:
                return row
        return None

    def _out(self, raw: dict[str, Any], model: ManagedModel | None) -> ContainerOut:
        runtime = self._manager.models.get(model.name) if model else None
        return ContainerOut(
            **raw,
            registered_as=model.name if model else None,
            model_state=runtime.state.value if runtime else None,
        )

    async def list(self, server_name: str) -> list[ContainerOut]:
        """Every container the agent manages, with the model registered for each."""
        server, agent = await self._agent(server_name)
        raw: list[dict[str, Any]] = await agent.call("GET", "/containers")
        return [
            self._out(item, await self._backing_model(server, item["name"], item.get("port")))
            for item in raw
        ]

    async def host(self, server_name: str) -> HostOut:
        """GPU, memory and disk figures of the server."""
        _, agent = await self._agent(server_name)
        return HostOut.model_validate(await agent.call("GET", "/host"))

    async def logs(self, server_name: str, container: str, tail: int) -> LogsOut:
        """The last lines a container printed."""
        _, agent = await self._agent(server_name)
        return LogsOut.model_validate(
            await agent.call("GET", f"/containers/{container}/logs", params={"tail": tail})
        )

    async def create(
        self, server_name: str, body: ContainerCreate, *, actor: str, ip: str | None
    ) -> ContainerOut:
        """Create a container; with ``register_as`` also register it as a model."""
        server, agent = await self._agent(server_name)
        if max(body.gpus) >= server.gpu_count:
            raise InvalidInputError(
                f"{server_name} has {server.gpu_count} GPU(s), numbered 0 to {server.gpu_count - 1}"
            )
        if body.register_as is not None:
            await self._models.ensure_name_free(body.register_as.name, body.register_as.served_name)
        payload = body.model_dump(exclude={"register_as"}, exclude_none=True)
        for secret in ("api_key", "hf_token"):
            if secret in payload:
                payload[secret] = payload[secret].get_secret_value()
        raw = await agent.call("POST", "/containers", json=payload, change=True)
        await self._audit.record(
            actor,
            "container.create",
            target=f"{server_name}/{body.name}",
            ip=ip,
            detail=f"{body.image} on GPU {sorted(body.gpus)}, port {body.port}",
        )
        model: ManagedModel | None = None
        if body.register_as is not None:
            reg = body.register_as
            model = await self._models.create(
                ModelCreate(
                    name=reg.name,
                    server=server_name,
                    url=reg.url,
                    served_name=reg.served_name,
                    gpus=frozenset(body.gpus),
                    idle_minutes=reg.idle_minutes,
                    priority=reg.priority,
                    backend_api_key=body.api_key,
                    container=body.name,
                ),
                actor=actor,
                ip=ip,
            )
        return self._out(raw, model)

    async def _change(
        self,
        server_name: str,
        container: str,
        verb: str,
        *,
        actor: str,
        ip: str | None,
    ) -> ContainerOut:
        server, agent = await self._agent(server_name)
        current: dict[str, Any] = await agent.call("GET", f"/containers/{container}")
        model = await self._backing_model(server, container, current.get("port"))
        if model is not None and verb in {"stop", "restart"}:
            self._manager.require_quiet(model.name, verb)
        raw: dict[str, Any] = await agent.call(
            "POST", f"/containers/{container}/{verb}", change=True
        )
        await self._audit.record(
            actor, f"container.{verb}", target=f"{server_name}/{container}", ip=ip
        )
        if model is not None:
            await self._manager.refresh(model.name)
        return self._out(raw, model)

    async def start(
        self, server_name: str, container: str, *, actor: str, ip: str | None
    ) -> ContainerOut:
        """Start a stopped container."""
        return await self._change(server_name, container, "start", actor=actor, ip=ip)

    async def stop(
        self, server_name: str, container: str, *, actor: str, ip: str | None
    ) -> ContainerOut:
        """Stop a container (refused while its model is busy)."""
        return await self._change(server_name, container, "stop", actor=actor, ip=ip)

    async def restart(
        self, server_name: str, container: str, *, actor: str, ip: str | None
    ) -> ContainerOut:
        """Restart a container (refused while its model is busy)."""
        return await self._change(server_name, container, "restart", actor=actor, ip=ip)

    async def remove(
        self,
        server_name: str,
        container: str,
        *,
        remove_model: bool,
        actor: str,
        ip: str | None,
    ) -> None:
        """Delete a container. If a model is registered for it, ``remove_model`` must be true."""
        server, agent = await self._agent(server_name)
        current: dict[str, Any] = await agent.call("GET", f"/containers/{container}")
        model = await self._backing_model(server, container, current.get("port"))
        if model is not None:
            if not remove_model:
                raise InvalidInputError(
                    f"{container} runs the registered model '{model.name}': removing the "
                    "container also removes that model, so confirm to continue"
                )
            self._manager.require_quiet(model.name, "remove its container")
            await self._manager.sleep_now(model.name)  # an awake model cannot be unregistered
            # The model goes first: nothing can be routed to a container that is being deleted.
            await self._models.remove(model.name, actor=actor, ip=ip)
        await agent.call("DELETE", f"/containers/{container}", change=True)
        detail = f"and its model '{model.name}'" if model is not None else None
        await self._audit.record(
            actor, "container.remove", target=f"{server_name}/{container}", ip=ip, detail=detail
        )
