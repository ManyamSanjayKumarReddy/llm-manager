"""The registry of managed models: stored in the database, mirrored in the scheduler."""

import httpx
from pydantic import SecretStr
from tortoise.exceptions import IntegrityError
from tortoise.expressions import Q

from llm_manager.core.errors import InvalidInputError, NotFoundError
from llm_manager.core.models_config import ModelSpec
from llm_manager.db.models import ManagedModel, Server
from llm_manager.engine import Manager
from llm_manager.schemas.models import ModelCheck, ModelCheckRequest, ModelCreate, ModelUpdate
from llm_manager.services.audit import AuditService

_PROBE_TIMEOUT_S = 5.0
_CLEARABLE = {"served_name", "backend_api_key", "container"}


def _to_spec(row: ManagedModel) -> ModelSpec:
    return ModelSpec(
        server=row.server.name,
        url=row.url,
        served_name=row.served_name,
        gpus=frozenset(row.gpus),
        idle_minutes=row.idle_minutes,
        priority=row.priority,
        backend_api_key=SecretStr(row.backend_api_key) if row.backend_api_key else None,
    )


class ModelStore:
    """Database access used while the application starts (before the scheduler exists)."""

    @staticmethod
    async def specs() -> dict[str, ModelSpec]:
        """Every registered model, by name."""
        rows = await ManagedModel.all().prefetch_related("server").order_by("name")
        return {row.name: _to_spec(row) for row in rows}


def _refused(response: httpx.Response | None) -> bool:
    """Did the container answer 401/403, i.e. object to the API key?"""
    return response is not None and response.status_code in {
        httpx.codes.UNAUTHORIZED,
        httpx.codes.FORBIDDEN,
    }


async def _server_for(name: str, gpus: frozenset[int]) -> Server:
    """The registered server ``name``, which must have every GPU in ``gpus``."""
    server = await Server.get_or_none(name=name)
    if server is None:
        raise InvalidInputError(f"server '{name}' is not registered: add it on the Servers page")
    if max(gpus) >= server.gpu_count:
        raise InvalidInputError(
            f"{name} has {server.gpu_count} GPU(s), numbered 0 to {server.gpu_count - 1}"
        )
    return server


async def _check_container_free(
    server: Server, container: str | None, *, ignore: str | None
) -> None:
    """One container backs at most one model."""
    if container is None:
        return
    query = ManagedModel.filter(server=server, container_name=container)
    if ignore is not None:
        query = query.exclude(name=ignore)
    taken = await query.first()
    if taken is not None:
        raise InvalidInputError(f"container '{container}' already runs the model '{taken.name}'")


class ModelService:
    """Registers, edits and removes models, keeping the database and the scheduler in step."""

    def __init__(self, manager: Manager, audit: AuditService, http: httpx.AsyncClient) -> None:
        self._manager = manager
        self._audit = audit
        self._http = http

    async def page(
        self, *, q: str | None, offset: int, limit: int
    ) -> tuple[list[ManagedModel], int]:
        """One page of registered models by name; ``q`` searches name and served name."""
        query = ManagedModel.all().prefetch_related("server")
        if q and q.strip():
            term = q.strip()
            query = query.filter(Q(name__icontains=term) | Q(served_name__icontains=term))
        total = await query.count()
        return await query.order_by("name").offset(offset).limit(limit), total

    async def ensure_name_free(self, name: str, served_name: str | None) -> None:
        """Refuse a name (or served name) another model already uses, before anything is built."""
        wanted = {name, served_name} - {None}
        for other in self._manager.models.values():
            if wanted & {other.name, other.served_name}:
                raise InvalidInputError(
                    f"the name '{name}' or its served name is already used by '{other.name}'"
                )
        if await ManagedModel.filter(name=name).exists():
            raise InvalidInputError(f"a model called '{name}' already exists")

    async def create(self, body: ModelCreate, *, actor: str, ip: str | None) -> ManagedModel:
        """Register an existing container. If it is awake it is put to sleep."""
        server = await _server_for(body.server, body.gpus)
        spec = ModelSpec(
            server=server.name,
            url=body.url,
            served_name=body.served_name,
            gpus=body.gpus,
            idle_minutes=body.idle_minutes,
            priority=body.priority,
            backend_api_key=body.backend_api_key,
        )
        await _check_container_free(server, body.container, ignore=None)
        await self._manager.register(body.name, spec)  # validates names and probes the container
        try:
            row = await ManagedModel.create(
                name=body.name,
                server=server,
                url=spec.url,
                served_name=spec.served_name,
                gpus=sorted(spec.gpus),
                idle_minutes=spec.idle_minutes,
                priority=spec.priority,
                backend_api_key=spec.backend_key,
                container_name=body.container,
            )
        except IntegrityError:
            await self._manager.remove(body.name)
            raise InvalidInputError("a model with that name already exists") from None
        await self._audit.record(
            actor, "model.register", target=body.name, ip=ip, detail=f"gpus {sorted(spec.gpus)}"
        )
        return row

    async def update(
        self, name: str, body: ModelUpdate, *, actor: str, ip: str | None
    ) -> ManagedModel:
        """Change a model's settings. Where it runs can only change while it is idle."""
        row = await ManagedModel.get_or_none(name=name).prefetch_related("server")
        if row is None:
            raise NotFoundError(f"model '{name}' is not registered")
        unknown = set(body.clear) - _CLEARABLE
        if unknown:
            raise InvalidInputError(f"cannot clear: {', '.join(sorted(unknown))}")
        changes = body.model_dump(exclude_unset=True, exclude={"clear"}, exclude_none=True)
        container = changes.pop("container", row.container_name)
        if "container" in body.clear:
            container = None
        merged = {
            "server": row.server.name,
            "url": row.url,
            "served_name": row.served_name,
            "gpus": frozenset(row.gpus),
            "idle_minutes": row.idle_minutes,
            "priority": row.priority,
            "backend_api_key": SecretStr(row.backend_api_key) if row.backend_api_key else None,
            **changes,
            **dict.fromkeys(set(body.clear) - {"container"}),
        }
        spec = ModelSpec.model_validate(merged)
        server = await _server_for(spec.server, spec.gpus)
        if spec.server != row.server.name and "container" not in body.model_fields_set:
            container = None  # the link was to a container on the old server
        await _check_container_free(server, container, ignore=name)
        await self._manager.update(name, spec)
        row.server = server
        row.url = spec.url
        row.served_name = spec.served_name
        row.gpus = sorted(spec.gpus)
        row.idle_minutes = spec.idle_minutes
        row.priority = spec.priority
        row.backend_api_key = spec.backend_key
        row.container_name = container
        await row.save()
        await self._audit.record(
            actor, "model.update", target=name, ip=ip, detail=", ".join(sorted(changes)) or None
        )
        return row

    async def remove(self, name: str, *, actor: str, ip: str | None) -> None:
        """Stop managing a model. Its container is not touched."""
        await self._manager.remove(name)
        await ManagedModel.filter(name=name).delete()
        await self._audit.record(actor, "model.remove", target=name, ip=ip)

    async def sleep(self, name: str, *, actor: str, ip: str | None) -> None:
        """Put an idle, awake model to sleep right now."""
        await self._manager.sleep_now(name)
        await self._audit.record(actor, "model.sleep", target=name, ip=ip)

    async def check(self, body: ModelCheckRequest) -> ModelCheck:
        """Look at a container without changing anything, and say what is missing."""
        spec = ModelSpec(url=body.url, gpus=frozenset({0}), backend_api_key=body.backend_api_key)
        key = spec.backend_key
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        problems: list[str] = []

        async def get(path: str) -> httpx.Response | None:
            try:
                return await self._http.get(
                    f"{spec.url}{path}", headers=headers, timeout=_PROBE_TIMEOUT_S
                )
            except httpx.HTTPError:
                return None

        health = await get("/health")
        if health is None or health.status_code != httpx.codes.OK:
            problems.append("cannot reach the container: is it running, and is the address right?")
            return ModelCheck(
                reachable=False,
                sleep_endpoints=False,
                state=None,
                served_models=[],
                served_name_found=None,
                key_accepted=None,
                problems=problems,
            )

        state: str | None = None
        refused = False
        sleeping = await get("/is_sleeping")
        refused = refused or _refused(sleeping)
        if sleeping is not None and sleeping.status_code == httpx.codes.OK:
            try:
                state = "asleep" if sleeping.json()["is_sleeping"] else "awake"
            except (ValueError, KeyError, TypeError):
                state = None
        if refused:
            problems.append(
                "the container refused the API key: check it, or enter the one the container "
                "was started with"
                if key
                else "the container wants an API key: enter the one it was started with"
            )
        elif state is None:
            problems.append(
                "sleep endpoints are missing: start the container with -e VLLM_SERVER_DEV_MODE=1 "
                "and --enable-sleep-mode"
            )

        served: list[str] = []
        listing = await get("/v1/models")
        refused = refused or _refused(listing)
        if listing is not None and listing.status_code == httpx.codes.OK:
            try:
                served = [str(m["id"]) for m in listing.json()["data"]]
            except (ValueError, KeyError, TypeError):
                served = []
        found = None
        if body.served_name and served:
            found = body.served_name in served
            if not found:
                problems.append(
                    f"the container serves {', '.join(served)}, not '{body.served_name}'"
                )
        return ModelCheck(
            reachable=True,
            sleep_endpoints=state is not None,
            state=state,
            served_models=served,
            served_name_found=found,
            key_accepted=None if not key else not refused,
            problems=problems,
        )
