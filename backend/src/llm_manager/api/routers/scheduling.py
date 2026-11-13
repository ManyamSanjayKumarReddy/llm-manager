"""The scheduler's timings: queue timeout, turn length, priority hold, preemption (admins only)."""

from fastapi import APIRouter, Request

from llm_manager.api.deps import AdminDep, ContainerDep, client_ip
from llm_manager.schemas.scheduler import SchedulerSettingsOut, SchedulerValues

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/scheduler")
async def get_scheduler(_: AdminDep, container: ContainerDep) -> SchedulerSettingsOut:
    """The timings in force now, with the built-in defaults."""
    return await container.scheduler_settings.get()


@router.put("/scheduler")
async def put_scheduler(
    body: SchedulerValues, request: Request, admin: AdminDep, container: ContainerDep
) -> SchedulerSettingsOut:
    """Save new timings; they apply to the running scheduler at once."""
    return await container.scheduler_settings.update(
        body, actor=admin.username, ip=client_ip(request, container)
    )
