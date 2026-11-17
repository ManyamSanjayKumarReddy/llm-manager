from pathlib import Path

import pytest
from pydantic import ValidationError

from wakeful_agent.docker import parse_inspect
from wakeful_agent.host import parse_meminfo, parse_nvidia_smi
from wakeful_agent.settings import Settings


def test_parse_inspect_of_a_running_container() -> None:
    item = {
        "Name": "/qwen",
        "Created": "2026-11-17T01:00:00Z",
        "State": {"Status": "running", "Running": True, "StartedAt": "2026-11-17T01:00:02Z"},
        "Config": {
            "Image": "vllm/vllm-openai:v0.10.1",
            "Labels": {
                "wakeful.managed": "true",
                "wakeful.port": "8026",
                "wakeful.gpus": "0,1",
                "wakeful.model": "a/b",
            },
        },
        "HostConfig": {"RestartPolicy": {"Name": "unless-stopped"}},
    }
    out = parse_inspect(item)
    assert (out.name, out.running, out.port, out.gpus, out.model) == (
        "qwen",
        True,
        8026,
        [0, 1],
        "a/b",
    )
    assert out.exit_code is None
    assert out.restart_policy == "unless-stopped"


def test_parse_inspect_of_a_stopped_container_that_never_started() -> None:
    out = parse_inspect(
        {
            "Name": "/x",
            "State": {
                "Status": "created",
                "Running": False,
                "ExitCode": 0,
                "StartedAt": "0001-01-01T00:00:00Z",
            },
            "Config": {"Image": "i", "Labels": {}},
            "HostConfig": {"RestartPolicy": {"Name": ""}},
        }
    )
    assert out.started_at is None
    assert out.restart_policy == "no"
    assert out.port is None
    assert out.gpus == []


def test_parse_inspect_reports_an_out_of_memory_kill() -> None:
    out = parse_inspect(
        {
            "Name": "/x",
            "State": {"Status": "exited", "Running": False, "ExitCode": 137, "OOMKilled": True},
            "Config": {"Image": "i", "Labels": {}},
        }
    )
    assert out.oom_killed is True
    assert out.exit_code == 137


def test_parse_nvidia_smi() -> None:
    text = (
        "0, NVIDIA GeForce RTX 5060 Ti, 1043, 16311, 3, 41\n"
        "1, NVIDIA GeForce RTX 5060 Ti, 15000, 16311, 97, [N/A]\n"
        "garbage line\n"
    )
    gpus = parse_nvidia_smi(text)
    assert [(g.index, g.memory_used_mb, g.utilization_pct, g.temperature_c) for g in gpus] == [
        (0, 1043, 3, 41),
        (1, 15000, 97, None),
    ]


def test_parse_meminfo() -> None:
    mem = parse_meminfo(
        "MemTotal:       65536000 kB\nMemAvailable:   20480000 kB\nSwapFree: 0 kB\n"
    )
    assert mem == {"MemTotal": 64000, "MemAvailable": 20000, "SwapFree": 0}


def test_the_token_must_be_long(cache_root: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(token="short", cache_roots=[cache_root])


def test_lists_can_be_comma_separated_in_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_TOKEN", "t" * 40)
    monkeypatch.setenv("AGENT_CACHE_ROOTS", "/data/a, /data/b")
    monkeypatch.setenv("AGENT_IMAGES", "vllm/vllm-openai")
    settings = Settings()
    assert settings.cache_roots == [Path("/data/a"), Path("/data/b")]
    assert settings.images == ["vllm/vllm-openai"]
