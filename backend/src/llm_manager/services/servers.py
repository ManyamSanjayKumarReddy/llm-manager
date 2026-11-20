"""The servers (machines with GPUs) that models are placed on."""

from datetime import UTC, datetime

from tortoise.exceptions import IntegrityError

from llm_manager.core import security
from llm_manager.core.errors import InvalidInputError, NotFoundError
from llm_manager.db.models import ManagedModel, Server
from llm_manager.schemas.servers import ServerCreate, ServerOut, ServerUpdate, TunnelEnrolled
from llm_manager.services.audit import AuditService
from llm_manager.services.tunnel import Hub

TUNNEL_PREFIX = "wkt_"
CONNECT_PATH = "/api/agent/connect"


class ServerService:
    """Registers, resizes and removes servers."""

    def __init__(self, audit: AuditService, hub: Hub) -> None:
        self._audit = audit
        self._hub = hub

    @staticmethod
    async def get(name: str) -> Server:
        """The server called ``name``, or a clear error."""
        row = await Server.get_or_none(name=name)
        if row is None:
            raise NotFoundError(f"server '{name}' is not registered: add it on the Servers page")
        return row

    async def _out(self, rows: list[Server]) -> list[ServerOut]:
        placed: dict[str, list[str]] = {}
        for model in await ManagedModel.all().prefetch_related("server").order_by("name"):
            placed.setdefault(model.server.name, []).append(model.name)
        out = []
        for r in rows:
            link = self._hub.info(r.name)
            out.append(
                ServerOut(
                    name=r.name,
                    gpu_count=r.gpu_count,
                    gpu_type=r.gpu_type,
                    agent_url=r.agent_url,
                    has_agent=bool(r.tunnel_token_hash or (r.agent_url and r.agent_token)),
                    tunnel=bool(r.tunnel_token_hash),
                    tunnel_connected=link.connected,
                    tunnel_last_seen=datetime.now(UTC) if link.connected else r.tunnel_last_seen,
                    tunnel_agent_version=link.agent_version,
                    models=placed.get(r.name, []),
                    created_at=r.created_at,
                )
            )
        return out

    async def list(self) -> list[ServerOut]:
        """Every server by name, with the models placed on it."""
        return await self._out(await Server.all().order_by("name"))

    async def create(self, body: ServerCreate, *, actor: str, ip: str | None) -> ServerOut:
        """Register a server."""
        if bool(body.agent_url) != bool(body.agent_token):
            raise InvalidInputError("an agent needs both an address and a token")
        try:
            row = await Server.create(
                name=body.name,
                gpu_count=body.gpu_count,
                gpu_type=body.gpu_type or None,
                agent_url=body.agent_url or None,
                agent_token=body.agent_token or None,
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
        if row.tunnel_token_hash and (body.agent_url or body.agent_token):
            raise InvalidInputError(
                f"the agent on {name} connects out: revoke that connection first to use an address"
            )
        if body.agent_url is not None:
            if body.agent_url == "":
                row.agent_url = row.agent_token = None  # removing the agent forgets its token
            else:
                row.agent_url = body.agent_url
            changed.append("agent address")
        if body.agent_token is not None:
            row.agent_token = body.agent_token
            changed.append("agent token")
        if bool(row.agent_url) != bool(row.agent_token):
            raise InvalidInputError("an agent needs both an address and a token")
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
        await self._hub.disable(name)
        await row.delete()
        await self._audit.record(actor, "server.remove", target=name, ip=ip)

    async def enroll_tunnel(self, name: str, *, actor: str, ip: str | None) -> TunnelEnrolled:
        """Issue (or replace) the token the server's agent uses to connect out.

        Replacing it closes the old connection, so the old token stops working at once. Any
        address and token stored for a direct agent are forgotten: calls now go down the connection.
        """
        row = await self.get(name)
        token = security.new_token(TUNNEL_PREFIX)
        row.tunnel_token_hash = security.digest(token)
        row.agent_url = row.agent_token = None
        await row.save()
        await self._hub.enable(name)
        await self._audit.record(actor, "server.tunnel_enroll", target=name, ip=ip)
        return TunnelEnrolled(token=token, connect_path=CONNECT_PATH)

    async def revoke_tunnel(self, name: str, *, actor: str, ip: str | None) -> ServerOut:
        """Stop accepting the server's agent (it is disconnected now and cannot come back)."""
        row = await self.get(name)
        if not row.tunnel_token_hash:
            raise InvalidInputError(f"{name} has no outbound connection")
        row.tunnel_token_hash = None
        await row.save()
        await self._hub.disable(name)
        await self._audit.record(actor, "server.tunnel_revoke", target=name, ip=ip)
        return (await self._out([row]))[0]

    @staticmethod
    async def authenticate(token: str) -> Server | None:
        """The server this enrollment token belongs to, or None."""
        return await Server.get_or_none(tunnel_token_hash=security.digest(token))
