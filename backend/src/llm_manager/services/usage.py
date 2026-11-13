"""Token and request usage, read from the per-day totals."""

from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from tortoise import Tortoise

from llm_manager.core.errors import NotFoundError
from llm_manager.db.models import ApiKey
from llm_manager.schemas.usage import (
    UsageDay,
    UsageKey,
    UsageKeyOut,
    UsageModel,
    UsageOut,
    UsageTotals,
)

_SUMS = """
    COALESCE(SUM(u.requests), 0) AS requests,
    COALESCE(SUM(u.errors), 0) AS errors,
    COALESCE(SUM(u.prompt_tokens), 0) AS prompt_tokens,
    COALESCE(SUM(u.completion_tokens), 0) AS completion_tokens
"""
_DAILY_SQL = f"""
SELECT u.day, {_SUMS}
FROM usage_daily u
WHERE u.day >= $1 AND ($2::uuid IS NULL OR u.api_key_id = $2::uuid)
GROUP BY u.day
"""  # noqa: S608 - only a constant is inserted
_MODELS_SQL = f"""
SELECT u.model, {_SUMS}
FROM usage_daily u
WHERE u.day >= $1 AND ($2::uuid IS NULL OR u.api_key_id = $2::uuid)
GROUP BY u.model
ORDER BY SUM(u.prompt_tokens + u.completion_tokens) DESC, u.model
"""  # noqa: S608
_KEYS_SQL = f"""
SELECT k.id, k.label, k.prefix, k.revoked_at, k.last_used_at, {_SUMS}
FROM api_keys k
LEFT JOIN usage_daily u ON u.api_key_id = k.id AND u.day >= $1
WHERE ($2::uuid IS NULL OR k.id = $2::uuid)
GROUP BY k.id
ORDER BY SUM(u.prompt_tokens + u.completion_tokens) DESC NULLS LAST, k.label
"""  # noqa: S608


def _numbers(row: dict[str, Any]) -> dict[str, int]:
    prompt, completion = int(row["prompt_tokens"]), int(row["completion_tokens"])
    return {
        "requests": int(row["requests"]),
        "errors": int(row["errors"]),
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


class UsageService:
    """Adds up the daily totals the recorder keeps."""

    @staticmethod
    def _start(days: int) -> date:
        """First UTC day of a window of ``days`` days that ends today."""
        return datetime.now(UTC).date() - timedelta(days=days - 1)

    async def _daily(self, days: int, key_id: UUID | None) -> list[UsageDay]:
        start = self._start(days)
        rows = await Tortoise.get_connection("default").execute_query_dict(
            _DAILY_SQL, [start, key_id]
        )
        found = {r["day"]: _numbers(r) for r in rows}
        empty = {"requests": 0, "errors": 0, "prompt_tokens": 0, "completion_tokens": 0,
                 "total_tokens": 0}  # fmt: skip
        return [
            UsageDay(day=day, **found.get(day, empty))
            for day in (start + timedelta(days=i) for i in range(days))
        ]

    @staticmethod
    async def _models(start: date, key_id: UUID | None) -> list[UsageModel]:
        rows = await Tortoise.get_connection("default").execute_query_dict(
            _MODELS_SQL, [start, key_id]
        )
        return [UsageModel(model=r["model"], **_numbers(r)) for r in rows]

    @staticmethod
    async def _keys(start: date, key_id: UUID | None) -> list[UsageKey]:
        rows = await Tortoise.get_connection("default").execute_query_dict(
            _KEYS_SQL, [start, key_id]
        )
        return [
            UsageKey(
                id=r["id"],
                label=r["label"],
                prefix=r["prefix"],
                revoked=r["revoked_at"] is not None,
                last_used_at=r["last_used_at"],
                **_numbers(r),
            )
            for r in rows
        ]

    async def overview(self, days: int) -> UsageOut:
        """Totals, a per-day series, and usage per key and per model over the last ``days``."""
        daily = await self._daily(days, None)
        start = self._start(days)
        totals = UsageTotals(
            **{
                f: sum(getattr(d, f) for d in daily)
                for f in (
                    "requests",
                    "errors",
                    "prompt_tokens",
                    "completion_tokens",
                    "total_tokens",
                )
            }
        )
        return UsageOut(
            days=days,
            totals=totals,
            daily=daily,
            keys=await self._keys(start, None),
            models=await self._models(start, None),
        )

    async def for_key(self, key_id: UUID, days: int) -> UsageKeyOut:
        """One key's usage: a per-day series and a per-model breakdown."""
        if not await ApiKey.filter(id=key_id).exists():
            raise NotFoundError("key not found")
        start = self._start(days)
        (key,) = await self._keys(start, key_id)
        return UsageKeyOut(
            key=key,
            days=days,
            daily=await self._daily(days, key_id),
            models=await self._models(start, key_id),
        )
