"""What the agent answers with."""

from pydantic import BaseModel


class ContainerOut(BaseModel):
    """A container this agent created."""

    name: str
    state: str  # running, exited, restarting, created, paused, dead
    running: bool
    status: str  # what docker would print, e.g. "Up 3 hours"
    image: str
    port: int | None
    gpus: list[int]
    model: str | None
    restart_policy: str
    exit_code: int | None
    oom_killed: bool
    created_at: str
    started_at: str | None


class LogsOut(BaseModel):
    """The tail of a container's output."""

    name: str
    text: str
    truncated: bool


class GpuOut(BaseModel):
    """One GPU as ``nvidia-smi`` reports it."""

    index: int
    name: str
    memory_used_mb: int
    memory_total_mb: int
    utilization_pct: int
    temperature_c: int | None


class HostOut(BaseModel):
    """How loaded this server is."""

    gpus: list[GpuOut]
    gpu_error: str | None
    ram_total_mb: int
    ram_available_mb: int
    swap_total_mb: int
    swap_used_mb: int
    disk_total_gb: float
    disk_free_gb: float
    disk_path: str
    cpu_count: int
    load_1m: float


class HealthOut(BaseModel):
    """Answer of the open health check."""

    ok: bool
    version: str
