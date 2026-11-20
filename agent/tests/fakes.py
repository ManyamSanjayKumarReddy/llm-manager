"""An in-memory Docker and host reader, so the agent is tested without Docker or GPUs."""

from wakeful_agent.errors import AgentError, NotFoundError
from wakeful_agent.schemas import ContainerOut, GpuOut, HostOut
from wakeful_agent.spec import LABEL_GPUS, LABEL_MODEL, LABEL_PORT, RunCommand


class FakeDocker:
    """Containers kept in a dict; ``foreign`` holds ones the agent did not create."""

    def __init__(self, images: set[str] | None = None) -> None:
        self.images = images if images is not None else {"vllm/vllm-openai:v0.10.1"}
        self.containers: dict[str, ContainerOut] = {}
        self.foreign: set[str] = {"production-db", "other-vllm"}
        self.runs: list[RunCommand] = []
        self.pulls: list[str] = []
        self.run_fails_after_creating = False
        self.unpullable: set[str] = set()
        self.calls: list[tuple[str, str]] = []

    def _managed(self, name: str) -> ContainerOut:
        if name not in self.containers:
            raise NotFoundError(name)
        return self.containers[name]

    async def list(self) -> list[ContainerOut]:
        return sorted(self.containers.values(), key=lambda c: c.name)

    async def get(self, name: str) -> ContainerOut:
        return self._managed(name)

    async def image_present(self, image: str) -> bool:
        return image in self.images

    async def pull(self, image: str) -> None:
        self.pulls.append(image)
        if image in self.unpullable:
            raise AgentError(f"docker pull failed: {image} not found", 502)
        self.images.add(image)

    async def run(self, command: RunCommand) -> None:
        self.runs.append(command)
        argv = command.argv
        name = argv[argv.index("--name") + 1]
        if name in self.foreign:
            raise AgentError("docker run failed: name already in use", 502)
        labels = {
            a.split("=", 1)[0]: a.split("=", 1)[1]
            for i, a in enumerate(argv)
            if i > 0 and argv[i - 1] == "--label" and "=" in a
        }
        self.containers[name] = ContainerOut(
            name=name,
            state="running",
            running=True,
            status="running",
            image=argv[argv.index("--ipc=host") + 1],
            port=int(labels[LABEL_PORT]),
            gpus=[int(g) for g in labels[LABEL_GPUS].split(",")],
            model=labels[LABEL_MODEL],
            restart_policy="unless-stopped" if "--restart" in argv else "no",
            exit_code=None,
            oom_killed=False,
            created_at="2026-11-17T00:00:00Z",
            started_at="2026-11-17T00:00:01Z",
        )
        if self.run_fails_after_creating:  # docker made the container, then could not start it
            raise AgentError("docker run failed: could not select device driver", 502)

    def _set(self, name: str, running: bool) -> None:
        old = self._managed(name)
        self.containers[name] = old.model_copy(
            update={
                "running": running,
                "state": "running" if running else "exited",
                "exit_code": None if running else 0,
            }
        )

    async def start(self, name: str) -> None:
        self._managed(name)
        self.calls.append(("start", name))
        self._set(name, running=True)

    async def stop(self, name: str) -> None:
        self._managed(name)
        self.calls.append(("stop", name))
        self._set(name, running=False)

    async def restart(self, name: str) -> None:
        self._managed(name)
        self.calls.append(("restart", name))
        self._set(name, running=True)

    async def remove(self, name: str) -> None:
        self._managed(name)
        self.calls.append(("remove", name))
        del self.containers[name]

    async def logs(self, name: str, tail: int) -> tuple[str, bool]:
        self._managed(name)
        return f"last {tail} lines of {name}\n", False


class FakeHost:
    """Fixed figures."""

    async def read(self) -> HostOut:
        return HostOut(
            gpus=[
                GpuOut(
                    index=0,
                    name="RTX 5060 Ti",
                    memory_used_mb=1000,
                    memory_total_mb=16311,
                    utilization_pct=3,
                    temperature_c=40,
                )
            ],
            gpu_error=None,
            ram_total_mb=64000,
            ram_available_mb=20000,
            swap_total_mb=26000,
            swap_used_mb=11000,
            disk_total_gb=900.0,
            disk_free_gb=400.0,
            disk_path="/root/.cache",
            cpu_count=16,
            load_1m=0.5,
        )
