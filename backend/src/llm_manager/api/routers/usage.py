"""How much each API key and model has been used (admins only)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from llm_manager.api.deps import AdminDep, ContainerDep
from llm_manager.schemas.usage import UsageKeyOut, UsageOut

router = APIRouter(prefix="/api/usage", tags=["usage"])

Days = Annotated[int, Query(ge=1, le=730)]


@router.get("")
async def usage(_: AdminDep, container: ContainerDep, days: Days = 30) -> UsageOut:
    """Requests and tokens over the last ``days`` days, by day, by API key and by model."""
    return await container.usage.overview(days)


@router.get("/keys/{key_id}")
async def key_usage(
    key_id: UUID, _: AdminDep, container: ContainerDep, days: Days = 30
) -> UsageKeyOut:
    """One API key's requests and tokens over the last ``days`` days."""
    return await container.usage.for_key(key_id, days)
