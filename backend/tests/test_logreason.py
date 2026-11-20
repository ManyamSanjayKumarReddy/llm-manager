"""Reading a vLLM container's log: the one line that says why it failed."""

from llm_manager.services.logreason import clean_line, failure_reason, last_line

FREE_MEMORY = (
    "2026-11-20T05:10:28.100Z (EngineCore_0 pid=123) ERROR 11-20 05:10:28 [core.py:700] "
    "ValueError: Free memory on device (15.82/22.03 GiB) on startup is less than desired GPU "
    "memory utilization (0.9, 19.83 GiB). Decrease GPU memory utilization or reduce GPU memory "
    "used by other processes.\n"
    "2026-11-20T05:10:29.000Z (APIServer pid=1) RuntimeError: Engine core initialization "
    "failed. See root cause above. Failed core proc(s): {}\n"
)


def test_a_lines_noise_is_removed() -> None:
    line = (
        "2026-11-20T05:17:34.123456789Z (EngineCore_0 pid=122) INFO 11-20 05:17:34 "
        "[gpu_worker.py:115] Sleep mode freed 15.18 GiB memory"
    )
    assert clean_line(line) == "Sleep mode freed 15.18 GiB memory"
    assert clean_line("plain text") == "plain text"


def test_the_last_line_is_what_a_loading_container_is_doing() -> None:
    log = "first\n\n(APIServer pid=1) INFO 11-20 05:17:30 [x.py:1] Loading weights\n\n"
    assert last_line(log) == "Loading weights"
    assert last_line("   \n") is None


def test_not_enough_free_gpu_memory_is_explained_with_the_numbers() -> None:
    reason = failure_reason(FREE_MEMORY)
    assert reason is not None
    assert "15.82 of 22.03 GiB is free" in reason
    assert "19.83 GiB (90%" in reason
    assert "Lower the GPU memory share" in reason


def test_the_generic_wrapper_error_is_not_mistaken_for_the_cause() -> None:
    log = (
        "(EngineCore_0 pid=1) ERROR 11-20 05:10:28 [core.py:700] KeyError: 'foo'\n"
        "RuntimeError: Engine core initialization failed. See root cause above.\n"
    )
    assert failure_reason(log) == "KeyError: 'foo'"


def test_the_usual_causes_say_what_to_do() -> None:
    assert "ran out of memory" in (
        failure_reason("torch.OutOfMemoryError: CUDA out of memory") or ""
    )
    assert "port is already in use" in (
        failure_reason("OSError: [Errno 98] address already in use") or ""
    )
    assert "disk is full" in (failure_reason("OSError: [Errno 28] No space left on device") or "")
    assert "Hugging Face refused" in (failure_reason("huggingface_hub: 401 Client Error") or "")
    assert "NVIDIA container toolkit" in (
        failure_reason("docker: could not select device driver") or ""
    )


def test_a_log_with_no_error_gives_the_last_line_or_nothing() -> None:
    assert failure_reason("loading\nstill loading\n") == "still loading"
    assert failure_reason("") is None


def test_a_running_container_only_reports_real_errors() -> None:
    assert failure_reason("Loading weights\n", fallback=False) is None
    assert failure_reason("KeyError: 'x'\n", fallback=False) == "KeyError: 'x'"
