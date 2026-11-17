"""CliDocker against the real Docker on this machine.

Uses one uniquely named, labelled container and an image that is already present; it never
touches any other container. Skipped when Docker or the image is missing.
"""

import secrets
import shutil
import subprocess
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from wakeful_agent.docker import CliDocker
from wakeful_agent.errors import NotFoundError
from wakeful_agent.settings import Settings
from wakeful_agent.spec import RunCommand

IMAGE = "nginx:stable"  # has /bin/sleep; any local image with a sleep binary works


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=False)


pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None or _docker("image", "inspect", IMAGE).returncode != 0,
    reason=f"needs Docker and the {IMAGE} image",
)


@pytest_asyncio.fixture
async def names() -> AsyncIterator[tuple[str, str]]:
    managed = f"wakeful-agent-test-{secrets.token_hex(4)}"
    foreign = f"wakeful-agent-foreign-{secrets.token_hex(4)}"
    _docker("run", "-d", "--name", foreign, "--entrypoint", "sleep", IMAGE, "300")
    yield managed, foreign
    _docker("rm", "-f", managed, foreign)


def run_command(name: str) -> RunCommand:
    return RunCommand(
        argv=[
            "run", "-d", "--name", name,
            "--label", "wakeful.managed=true", "--label", "wakeful.port=8123",
            "--label", "wakeful.gpus=0,1", "--label", "wakeful.model=a/b",
            "--restart", "unless-stopped", "--init", "-e", "SECRET_FROM_ENV",
            "--entrypoint", "sleep", IMAGE, "300",
        ],
        env={"SECRET_FROM_ENV": "s3cret"},
        port=8123,
    )  # fmt: skip


async def test_full_life_of_a_container(names: tuple[str, str]) -> None:
    managed, _ = names
    docker = CliDocker(Settings(token="t" * 40))

    assert await docker.image_present(IMAGE)
    assert not await docker.image_present("no-such/image:1")

    await docker.run(run_command(managed))
    info = await docker.get(managed)
    assert info.running
    assert (info.port, info.gpus, info.model) == (8123, [0, 1], "a/b")
    assert info.restart_policy == "unless-stopped"
    assert managed in [c.name for c in await docker.list()]

    # the secret reached the container through the environment, not the argument list
    shown = _docker("inspect", "--format", "{{json .Config.Cmd}}{{json .Args}}", managed).stdout
    assert "s3cret" not in shown

    await docker.stop(managed)
    assert not (await docker.get(managed)).running
    await docker.start(managed)
    assert (await docker.get(managed)).running
    await docker.restart(managed)
    assert (await docker.get(managed)).running

    text, truncated = await docker.logs(managed, 10)
    assert isinstance(text, str)
    assert truncated is False

    await docker.remove(managed)
    with pytest.raises(NotFoundError):
        await docker.get(managed)


async def test_a_container_without_the_label_is_untouchable(names: tuple[str, str]) -> None:
    _, foreign = names
    docker = CliDocker(Settings(token="t" * 40))
    assert foreign not in [c.name for c in await docker.list()]
    for action in (docker.get, docker.start, docker.stop, docker.restart, docker.remove):
        with pytest.raises(NotFoundError):
            await action(foreign)
    with pytest.raises(NotFoundError):
        await docker.logs(foreign, 5)
    assert _docker("inspect", "--format", "{{.State.Running}}", foreign).stdout.strip() == "true"
