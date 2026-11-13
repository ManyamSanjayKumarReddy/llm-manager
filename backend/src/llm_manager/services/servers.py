"""The servers (machines with GPUs) that models are placed on."""

from tortoise.exceptions import IntegrityError

from llm_manager.core.errors import InvalidInputError, NotFoundError
from llm_manager.db.models import ManagedModel, Server
from llm_manager.schemas.servers import ServerCreate, ServerOut, ServerUpdate
from llm_manager.services.audit import AuditService


class ServerService:
    """Registers, resizes and removes servers."""

    def __init__(self, audit: AuditService) -> None:
        self._audit = audit

    @staticmethod
    async def get(name: str) -> Server:
        """The server called ``name``, or a clear error."""
        row = await Server.get_or_none(name=name)
        if row is None:
            raise NotFoundError(f"server '{name}' is not registered: add it on the Servers page")
        return row

    @staticmethod
    async def _out(rows: list[Server]) -> list[ServerOut]:
        placed: dict[str, list[str]] = {}
        for model in await ManagedModel.all().prefetch_related("server").order_by("name"):
            placed.setdefault(model.server.name, []).append(model.name)
        return [
            ServerOut(
                name=r.name,
                gpu_count=r.gpu_count,
                gpu_type=r.gpu_type,
                models=placed.get(r.name, []),
                created_at=r.created_at,
            )
            for r in rows
        ]

    async def list(self) -> list[ServerOut]:
        """Every server by name, with the models placed on it."""
        return await self._out(await Server.all().order_by("name"))

    async def create(self, body: ServerCreate, *, actor: str, ip: str | None) -> ServerOut:
        """Register a server."""
        try:
            row = await Server.create(
                name=body.name, gpu_count=body.gpu_count, gpu_type=body.gpu_type or None
            )
        except IntegrityError:
            raise InvalidInputError("a server with that name already exists") from None
        await self._audit.record(
            actor, "server.add", target=body.name, ip=ip, detail=f"{body.gpu_count} GPUs"
        )
        return (await self._out([row]))[0]

    async def update(
        self, name: str, body: ServerUpdate, *, actor: str, ip: str | None
    ) -> ServerOut:
        """Change the GPU count (never below what its models already use) or the GPU type."""
        row = await self.get(name)
        changed = []
        if body.gpu_count is not None:
            used = max(
                (g for m in await ManagedModel.filter(server=row) for g in m.gpus), default=-1
            )
            if body.gpu_count <= used:
                raise InvalidInputError(
                    f"models on {name} already use GPU {used}: move them first, or keep at "
                    f"least {used + 1} GPUs"
                )
            row.gpu_count = body.gpu_count
            changed.append(f"{body.gpu_count} GPUs")
        if body.gpu_type is not None:
            row.gpu_type = body.gpu_type.strip() or None
            changed.append("gpu type")
        await row.save()
        await self._audit.record(
            actor, "server.update", target=name, ip=ip, detail=", ".join(changed) or None
        )
        return (await self._out([row]))[0]

    async def remove(self, name: str, *, actor: str, ip: str | None) -> None:
        """Delete a server that has no models."""
        row = await self.get(name)
        if await ManagedModel.filter(server=row).exists():
            raise InvalidInputError(f"{name} still has models: remove or move them first")
        await row.delete()
        await self._audit.record(actor, "server.remove", target=name, ip=ip)
