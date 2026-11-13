"""Periodic cleanup of expired sessions and old history."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from tortoise.exceptions import BaseORMException

from llm_manager.core.settings import Settings
from llm_manager.db.models import AuditLog, Event, RequestLog, Session, UsageDaily

log = logging.getLogger(__name__)

_INTERVAL_S = 3600.0


async def cleanup(settings: Settings) -> None:
    """Delete expired sessions and history older than the retention settings."""
    now = datetime.now(UTC)
    history_cutoff = now - timedelta(days=settings.retention_days)
    await Session.filter(expires_at__lt=now).delete()
    await RequestLog.filter(ts__lt=history_cutoff).delete()
    await Event.filter(ts__lt=history_cutoff).delete()
    await UsageDaily.filter(
        day__lt=(now - timedelta(days=settings.usage_retention_days)).date()
    ).delete()
    await AuditLog.filter(ts__lt=now - timedelta(days=settings.audit_retention_days)).delete()


async def run_maintenance(settings: Settings) -> None:
    """Run ``cleanup`` hourly until cancelled."""
    while True:
        try:
            await cleanup(settings)
        except BaseORMException:
            log.exception("maintenance cleanup failed")
        await asyncio.sleep(_INTERVAL_S)
