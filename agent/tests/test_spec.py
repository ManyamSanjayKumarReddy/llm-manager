import json
from pathlib import Path

import pytest

from wakeful_agent.errors import SpecError
from wakeful_agent.settings import Settings
from wakeful_agent.spec import ContainerSpec, build_run

GOLDEN = json.loads((Path(__file__).parent / "golden_commands.json").read_text())


def make(cache_root: Path, **changes: object) -> ContainerSpec:
    base: dict[str, object] = {
        "name": "qwen",
        "model": "Qwen/Qwen2.5-7B-Instruct",
        "image": "vllm/vllm-openai:v0.10.1",
        "port": 8026,
        "gpus": [0],
        "cache_dir": str(cache_root / "hf"),
    }
    return ContainerSpec.model_validate({**base, **changes})


def without_labels(argv: list[str]) -> list[str]:
    out: list[str] = []
    skip = False
    for i, a in enumerate(argv):
        if skip:
            skip = False
        elif a == "--label":
            skip = True
        else:
            out.append(a)
        _ = i
    return out


@pytest.mark.parametrize("case", GOLDEN, ids=[c["name"] for c in GOLDEN])
def test_matches_the_command_the_dashboard_shows(case: dict[str, object]) -> None:
    settings = Settings(token="t" * 40, cache_roots=[Path("/data")])
    spec = ContainerSpec.model_validate(case["spec"])
    command = build_run(spec, settings)
    assert without_labels(command.argv) == case["argv"]


def test_labels_mark_the_container_as_managed(settings: Settings, cache_root: Path) -> None:
    argv = build_run(make(cache_root), settings).argv
    labels = [argv[i + 1] for i, a in enumerate(argv) if a == "--label"]
    assert labels == [
        "wakeful.managed=true",
        "wakeful.port=8026",
        "wakeful.gpus=0",
        "wakeful.model=Qwen/Qwen2.5-7B-Instruct",
    ]


def test_secrets_stay_out_of_the_arguments(settings: Settings, cache_root: Path) -> None:
    command = build_run(
        make(cache_root, api_key="sk-secret-value", hf_token="hf_secret_token"), settings
    )
    assert "sk-secret-value" not in " ".join(command.argv)
    assert "hf_secret_token" not in " ".join(command.argv)
    assert command.env == {
        "VLLM_API_KEY": "sk-secret-value",
        "HUGGING_FACE_HUB_TOKEN": "hf_secret_token",
    }
    assert "VLLM_API_KEY" in command.argv


def test_memory_and_cpu_limits(settings: Settings, cache_root: Path) -> None:
    argv = build_run(make(cache_root, memory_gb=40, cpus=4), settings).argv
    assert argv[argv.index("--memory") + 1] == "40g"
    assert argv[argv.index("--memory-swap") + 1] == "40g"
    assert argv[argv.index("--cpus") + 1] == "4"


def test_the_port_is_only_published_on_localhost(settings: Settings, cache_root: Path) -> None:
    argv = build_run(make(cache_root), settings).argv
    assert argv[argv.index("-p") + 1] == "127.0.0.1:8026:8000"


@pytest.mark.parametrize(
    "image",
    [
        "evil/miner:latest",
        "vllm/vllm-openai",  # no tag
        "vllm/vllm-openai:latest;rm",
        "registry.evil.com/vllm/vllm-openai:v1",
        "VLLM/vllm-openai:v1",
    ],
)
def test_images_outside_the_allowlist_are_refused(
    settings: Settings, cache_root: Path, image: str
) -> None:
    with pytest.raises(SpecError, match="image"):
        build_run(make(cache_root, image=image), settings)


def test_the_patched_image_is_allowed(settings: Settings, cache_root: Path) -> None:
    spec = make(cache_root, image="vllm-openai:v0.10.1-abortsleep")
    assert "vllm-openai:v0.10.1-abortsleep" in build_run(spec, settings).argv


@pytest.mark.parametrize("path", ["/etc", "/", "/root", "relative/dir", "/data/../etc"])
def test_cache_folders_outside_the_roots_are_refused(settings: Settings, path: str) -> None:
    spec = ContainerSpec.model_validate(
        {
            "name": "x",
            "model": "a/b",
            "image": "vllm/vllm-openai:v1",
            "port": 8000 + 26,
            "gpus": [0],
            "cache_dir": path,
        }
    )
    with pytest.raises(SpecError, match="cache folder"):
        build_run(spec, settings)


def test_a_symlink_cannot_escape_the_cache_root(settings: Settings, cache_root: Path) -> None:
    (cache_root / "escape").symlink_to("/etc")
    with pytest.raises(SpecError, match="cache folder"):
        build_run(make(cache_root, cache_dir=str(cache_root / "escape")), settings)


@pytest.mark.parametrize("bad", ["a b", "a:b", "a,b", "a\nb"])
def test_cache_folder_characters_that_split_a_mount_are_refused(
    settings: Settings, cache_root: Path, bad: str
) -> None:
    with pytest.raises(SpecError, match="cache folder"):
        build_run(make(cache_root, cache_dir=f"{cache_root}/{bad}"), settings)


@pytest.mark.parametrize(
    "extra",
    ["--api-key=x", "--host 1.2.3.4", "--trust-remote-code", "--port 9", "--model other/x"],
)
def test_flags_the_agent_sets_cannot_be_repeated(
    settings: Settings, cache_root: Path, extra: str
) -> None:
    with pytest.raises(SpecError, match="cannot be repeated"):
        build_run(make(cache_root, extra_args=extra), settings)


@pytest.mark.parametrize("extra", ["; rm -rf /", "$(id)", "`id`", "--x 'y'", '--x "y"', "a|b"])
def test_shell_characters_in_extra_arguments_are_refused(
    settings: Settings, cache_root: Path, extra: str
) -> None:
    with pytest.raises(SpecError, match="extra arguments"):
        build_run(make(cache_root, extra_args=extra), settings)


@pytest.mark.parametrize("secret", ["has space", "new\nline", "x" * 600])
def test_secrets_must_be_one_plain_line(settings: Settings, cache_root: Path, secret: str) -> None:
    with pytest.raises(SpecError):
        build_run(make(cache_root, api_key=secret), settings)


@pytest.mark.parametrize("gpus", [[0, 0], [-1], [16]])
def test_gpu_numbers_must_be_distinct_and_in_range(
    settings: Settings, cache_root: Path, gpus: list[int]
) -> None:
    with pytest.raises(SpecError, match="gpus"):
        build_run(make(cache_root, gpus=gpus), settings)


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "-bad"},
        {"name": "a b"},
        {"name": "x;y"},
        {"model": "a/b/c"},
        {"model": "--evil"},
        {"port": 80},
        {"port": 70000},
        {"gpus": []},
        {"memory_share": 1.5},
        {"max_model_len": 10},
        {"tool_parser": "Bad Parser"},
        {"unknown_field": 1},
    ],
)
def test_malformed_specs_do_not_validate(cache_root: Path, changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):  # noqa: PT011
        make(cache_root, **changes)
