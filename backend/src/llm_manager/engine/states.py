"""Runtime state of one managed model."""

import time
from dataclasses import dataclass, field
from enum import StrEnum

from llm_manager.core.models_config import ModelSpec


class State(StrEnum):
    """Where a model's container is in its wake/sleep cycle."""

    ASLEEP = "asleep"  # weights in CPU RAM, GPU nearly empty
    WAKING = "waking"
    AWAKE = "awake"  # serving requests
    SLEEPING = "sleeping"
    DOWN = "down"  # container unreachable


# States in which a model still occupies GPU memory.
HOLDS_GPU = frozenset({State.AWAKE, State.WAKING, State.SLEEPING})


@dataclass
class ModelRuntime:
    """A model's live state plus statistics (statistics reset when the router restarts)."""

    name: str
    spec: ModelSpec
    state: State = State.DOWN
    inflight: int = 0  # requests being served right now
    waiting: int = 0  # requests waiting for this model to become ready
    last_used: float = field(default_factory=time.monotonic)
    awake_since: float = field(default_factory=time.monotonic)

    requests: int = 0
    errors: int = 0  # upstream answered >= 400, or was unreachable
    rejected: int = 0  # the router answered 503
    wakes: int = 0
    wake_total_s: float = 0.0
    last_wake_s: float | None = None
    sleeps: int = 0
    waits: int = 0  # requests that had to wait for a wake or a swap
    wait_total_s: float = 0.0
    wait_max_s: float = 0.0

    @property
    def served_name(self) -> str:
        """The model name vLLM itself expects in request bodies."""
        return self.spec.served_name or self.name
