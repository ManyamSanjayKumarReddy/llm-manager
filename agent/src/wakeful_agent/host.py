"""GPU, memory and disk figures for this server (read-only)."""

import asyncio
import os
import shutil
from pathlib import Path

from wakeful_agent.schemas import GpuOut, HostOut
from wakeful_agent.settings import Settings

_MB = 1024 * 1024
_GB = 1024**3
_QUERY = "index,name,memory.used,memory.total,utilization.gpu,temperature.gpu"


def _int(text: str) -> int | None:
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_nvidia_smi(output: str) -> list[GpuOut]:
    """Rows of ``--format=csv,noheader,nounits`` as GPUs; unreadable rows are skipped."""
    gpus: list[GpuOut] = []
    for line in output.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 6:
            continue
        index, used, total, util = (_int(parts[0]), _int(parts[2]), _int(parts[3]), _int(parts[4]))
        if index is None or used is None or total is None:
            continue
        gpus.append(
            GpuOut(
                index=index,
                name=parts[1],
                memory_used_mb=used,
                memory_total_mb=total,
                utilization_pct=util or 0,
                temperature_c=_int(parts[5]),
            )
        )
    return gpus


def parse_meminfo(text: str) -> dict[str, int]:
    """``/proc/meminfo`` as megabytes by field name."""
    values: dict[str, int] = {}
    for line in text.splitlines():
        name, _, rest = line.partition(":")
        number = rest.split()[0] if rest.split() else ""
        if number.isdigit():
            values[name] = int(number) // 1024  # the file is in kB
    return values


class HostInfo:
    """Reads the figures; subclass or replace in tests."""

    def __init__(self, settings: Settings) -> None:
        self._smi = settings.nvidia_smi_bin
        self._timeout = settings.command_timeout_s
        self._disk_path = next(iter(settings.cache_roots), Path("/"))

    async def _gpus(self) -> tuple[list[GpuOut], str | None]:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._smi,
                f"--query-gpu={_QUERY}",
                "--format=csv,noheader,nounits",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), self._timeout)
        except (OSError, TimeoutError) as error:
            return [], f"nvidia-smi is not available: {error}"
        if proc.returncode:
            return [], err.decode(errors="replace").strip()[:300] or "nvidia-smi failed"
        return parse_nvidia_smi(out.decode(errors="replace")), None

    def _memory(self) -> dict[str, int]:
        try:
            return parse_meminfo(Path("/proc/meminfo").read_text())
        except OSError:
            return {}

    def _disk(self) -> tuple[float, float, str]:
        path = self._disk_path
        while not path.exists() and path != path.parent:
            path = path.parent
        usage = shutil.disk_usage(path)
        return usage.total / _GB, usage.free / _GB, str(self._disk_path)

    async def read(self) -> HostOut:
        """The current figures."""
        gpus, gpu_error = await self._gpus()
        mem = self._memory()
        total, free, path = self._disk()
        try:
            load = os.getloadavg()[0]
        except OSError:
            load = 0.0
        return HostOut(
            gpus=gpus,
            gpu_error=gpu_error,
            ram_total_mb=mem.get("MemTotal", 0),
            ram_available_mb=mem.get("MemAvailable", 0),
            swap_total_mb=mem.get("SwapTotal", 0),
            swap_used_mb=mem.get("SwapTotal", 0) - mem.get("SwapFree", 0),
            disk_total_gb=round(total, 1),
            disk_free_gb=round(free, 1),
            disk_path=path,
            cpu_count=os.cpu_count() or 1,
            load_1m=round(load, 2),
        )
