"""Schemas for token and request usage per API key and model."""

from datetime import date, datetime
from uuid import UUID

from llm_manager.schemas.base import ResponseSchema


class UsageTotals(ResponseSchema):
    """Requests and tokens added up over some period."""

    requests: int
    errors: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class UsageDay(UsageTotals):
    """One UTC day (days without traffic are included, with zeros)."""

    day: date


class UsageModel(UsageTotals):
    """Usage of one model."""

    model: str


class UsageKey(UsageTotals):
    """Usage of one API key (keys that were not used in the period are listed with zeros)."""

    id: UUID
    label: str
    prefix: str
    revoked: bool
    last_used_at: datetime | None


class UsageOut(ResponseSchema):
    """Everything on the Usage page."""

    days: int
    totals: UsageTotals
    daily: list[UsageDay]
    keys: list[UsageKey]
    models: list[UsageModel]


class UsageKeyOut(ResponseSchema):
    """One API key's usage."""

    key: UsageKey
    days: int
    daily: list[UsageDay]
    models: list[UsageModel]
