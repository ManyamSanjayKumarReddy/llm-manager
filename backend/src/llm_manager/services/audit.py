"""The audit trail: who did what, from where."""

from tortoise.expressions import Q

from llm_manager.db.models import AuditLog

_MAX_ACTOR_LENGTH = 100


class AuditService:
    """Writes and reads audit log entries."""

    async def record(
        self,
        actor: str,
        action: str,
        *,
        target: str | None = None,
        ip: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Append one entry."""
        await AuditLog.create(
            actor=actor[:_MAX_ACTOR_LENGTH], action=action, target=target, ip=ip, detail=detail
        )

    async def page(self, *, q: str | None, offset: int, limit: int) -> tuple[list[AuditLog], int]:
        """Newest entries first; ``q`` matches the actor, action, target or detail."""
        query = AuditLog.all()
        if q and q.strip():
            term = q.strip()
            query = query.filter(
                Q(actor__icontains=term)
                | Q(action__icontains=term)
                | Q(target__icontains=term)
                | Q(detail__icontains=term)
            )
        total = await query.count()
        return await query.order_by("-id").offset(offset).limit(limit), total
