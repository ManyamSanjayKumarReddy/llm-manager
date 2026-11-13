"""The scheduler's timings: stored in the database, applied to the running scheduler at once."""

from llm_manager.core.models_config import EngineConfig
from llm_manager.core.settings import Settings
from llm_manager.db.models import SchedulerSettings
from llm_manager.engine import Manager
from llm_manager.schemas.scheduler import SchedulerSettingsOut, SchedulerValues
from llm_manager.services.audit import AuditService

_ROW_ID = 1


async def stored_engine_config(settings: Settings) -> EngineConfig:
    """The saved timings, or the environment's values when nobody has saved any yet."""
    row = await SchedulerSettings.get_or_none(id=_ROW_ID)
    if row is None:
        return settings.engine
    return SchedulerValues(
        queue_timeout_s=row.queue_timeout_s,
        min_awake_s=row.min_awake_s,
        priority_hold_s=row.priority_hold_s,
        preempt_after_s=row.preempt_after_s,
        wake_timeout_s=row.wake_timeout_s,
        sleep_timeout_s=row.sleep_timeout_s,
        reaper_interval_s=row.reaper_interval_s,
        sleep_level=row.sleep_level,
    ).to_engine()


class SchedulerSettingsService:
    """Reads and changes the scheduler's timings (admins only)."""

    def __init__(self, manager: Manager, audit: AuditService) -> None:
        self._manager = manager
        self._audit = audit

    async def get(self) -> SchedulerSettingsOut:
        """The timings in force, the built-in defaults, and who saved last."""
        row = await SchedulerSettings.get_or_none(id=_ROW_ID)
        return SchedulerSettingsOut(
            values=SchedulerValues.from_engine(self._manager.config),
            defaults=SchedulerValues.from_engine(EngineConfig()),
            updated_at=row.updated_at if row else None,
            updated_by=row.updated_by if row else None,
        )

    async def update(
        self, values: SchedulerValues, *, actor: str, ip: str | None
    ) -> SchedulerSettingsOut:
        """Save new timings and apply them to the running scheduler."""
        before = SchedulerValues.from_engine(self._manager.config).model_dump()
        after = values.model_dump()
        await SchedulerSettings.update_or_create(
            id=_ROW_ID, defaults={**after, "updated_by": actor}
        )
        await self._manager.reconfigure(values.to_engine())
        changed = [f"{k}={after[k]}" for k in after if after[k] != before[k]]
        await self._audit.record(
            actor,
            "settings.scheduler",
            target="scheduler",
            ip=ip,
            detail=", ".join(changed) or None,
        )
        return await self.get()
