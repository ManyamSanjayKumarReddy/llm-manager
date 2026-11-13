"""Schemas for the scheduler settings admins can change."""

from datetime import datetime
from typing import Annotated, Self

from pydantic import Field, model_validator

from llm_manager.core.models_config import EngineConfig
from llm_manager.schemas.base import RequestSchema, ResponseSchema

_DAY_S = 86_400.0
Seconds = Annotated[float, Field(gt=0, le=_DAY_S)]
HoldSeconds = Annotated[float, Field(ge=0, le=_DAY_S)]


class SchedulerValues(RequestSchema):
    """Every timing the scheduler uses, in seconds."""

    queue_timeout_s: Seconds = Field(description="longest a request waits for its model")
    min_awake_s: HoldSeconds = Field(description="a model's turn when another model is waiting")
    priority_hold_s: HoldSeconds = Field(description="grace for a busy higher-priority model")
    preempt_after_s: Seconds | None = Field(
        description="a request that waited this long stops a lower-priority running request; "
        "empty = never stop a running request"
    )
    wake_timeout_s: Seconds = Field(description="longest one wake-up call may take")
    sleep_timeout_s: Seconds = Field(description="longest one sleep call may take")
    reaper_interval_s: Seconds = Field(description="how often idle models are checked")
    sleep_level: int = Field(ge=1, le=2, description="1 keeps weights in CPU RAM (fast wake)")

    @model_validator(mode="after")
    def _preempt_before_timeout(self) -> Self:
        if self.preempt_after_s is not None and self.preempt_after_s >= self.queue_timeout_s:
            raise ValueError("preempt_after_s must be smaller than queue_timeout_s")
        return self

    def to_engine(self) -> EngineConfig:
        """The same values as the scheduler's own config."""
        return EngineConfig(**self.model_dump())

    @classmethod
    def from_engine(cls, config: EngineConfig) -> Self:
        """The scheduler's config as settings values."""
        return cls(**config.model_dump())


class SchedulerSettingsOut(ResponseSchema):
    """What is in force now, what 'reset' restores, and who changed it last."""

    values: SchedulerValues
    defaults: SchedulerValues
    updated_at: datetime | None
    updated_by: str | None
