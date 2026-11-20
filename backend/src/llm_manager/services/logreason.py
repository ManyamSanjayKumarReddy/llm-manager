"""Turn a vLLM container's log into one sentence a person can act on.

vLLM prints a hundred-line traceback when it fails; the cause is one line in it. These functions
find that line and, for the usual causes, say what to do about it. They only read text.
"""

import re

_TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z?\s+")
_PROCESS = re.compile(r"^\((?:\w+\s+)?pid=\d+\)\s*|^\(\w+ pid=\d+\)\s*")
_LEVEL = re.compile(
    r"^(?:INFO|WARNING|ERROR|DEBUG|CRITICAL)\s+\d\d-\d\d \d\d:\d\d:\d\d\s+(?:\[[^\]]*\]\s*)?"
)
_ERROR_LINE = re.compile(r"\b[A-Za-z_.]*(?:Error|Exception)\b: .+")
_NOT_THE_CAUSE = ("See root cause above", "Engine core initialization failed")
_MAX_LINE = 240

_FREE_MEMORY = re.compile(
    r"Free memory on device \(([\d.]+)/([\d.]+) GiB\).*?utilization \(([\d.]+), ([\d.]+) GiB\)"
)


def clean_line(line: str) -> str:
    """The message of one log line, without docker's timestamp, the process tag or the log level."""
    text = line.strip()
    text = _TIMESTAMP.sub("", text)
    text = _PROCESS.sub("", text)
    text = _LEVEL.sub("", text)
    return text.strip()


def _lines(log: str) -> list[str]:
    return [c for c in (clean_line(line) for line in log.splitlines()) if c]


def last_line(log: str) -> str | None:
    """The newest line with something in it (what a loading container is doing now)."""
    lines = _lines(log)
    if not lines:
        return None
    return lines[-1][:_MAX_LINE]


def failure_reason(log: str, *, fallback: bool = True) -> str | None:
    """Why the container stopped, from its log, or None when nothing in it says.

    Without ``fallback`` only an actual error is reported (never just the last line), which is what
    a container that is still running needs: its last line is usually just progress.
    """
    lines = _lines(log)
    text = "\n".join(lines)

    free = _FREE_MEMORY.search(text)
    if free:
        have, total, share, want = free.groups()
        return (
            f"Not enough free GPU memory: {have} of {total} GiB is free, but this model asked for "
            f"{want} GiB ({round(float(share) * 100)}% of the card). Lower the GPU "
            "memory share, or free the GPU (another program is using it)."
        )
    if re.search(r"CUDA out of memory|OutOfMemoryError", text):
        return (
            "The GPU ran out of memory while loading: lower the GPU memory share or the maximum "
            "context length, or use a smaller model."
        )
    if re.search(r"address already in use|port is already allocated", text, re.IGNORECASE):
        return "The port is already in use on that server: choose another port."
    if re.search(r"No space left on device", text):
        return "The disk is full: free some space (the model files are large)."
    if re.search(
        r"gated repo|Repository Not Found|Access to model .* is restricted|401 Client Error",
        text,
    ):
        return (
            "Hugging Face refused the download: the model is private or needs an access token "
            "(set a Hugging Face token) and its licence accepted."
        )
    if re.search(r"could not select device driver|nvidia-container|NVIDIA driver", text, re.I):
        return (
            "Docker could not give the container a GPU: is the NVIDIA container toolkit installed?"
        )

    candidates = [m.group(0) for line in lines if (m := _ERROR_LINE.search(line))]
    useful = [c for c in candidates if not any(skip in c for skip in _NOT_THE_CAUSE)]
    shortlist = useful or candidates
    if shortlist:
        return shortlist[-1][:_MAX_LINE]
    return lines[-1][:_MAX_LINE] if lines and fallback else None
