"""Reading token counts out of OpenAI-style responses, without slowing them down.

vLLM reports ``usage`` ({prompt_tokens, completion_tokens, total_tokens}) at the end of a JSON
reply, and in a final ``data:`` event of a stream when ``stream_options.include_usage`` is set.
Nothing here keeps prompts or answers: only the three numbers are read.
"""

import json
from dataclasses import dataclass
from typing import Any

_TAIL_BYTES = 16 * 1024  # `usage` sits at the very end of a JSON reply
_MAX_EVENT_BYTES = 1024 * 1024  # an SSE event larger than this is passed on without parsing
_STREAMED_PATHS = frozenset({"chat/completions", "completions"})


@dataclass(frozen=True)
class TokenUsage:
    """Tokens one request consumed."""

    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Prompt plus completion tokens."""
        return self.prompt_tokens + self.completion_tokens


def _from_object(value: Any) -> TokenUsage | None:
    """A TokenUsage from a decoded ``usage`` object, or None if it is not one."""
    if not isinstance(value, dict):
        return None
    prompt, completion = value.get("prompt_tokens"), value.get("completion_tokens")
    if not isinstance(prompt, int) or isinstance(prompt, bool) or prompt < 0:
        return None
    if completion is None:  # embeddings report only the prompt side
        completion = 0
    if not isinstance(completion, int) or isinstance(completion, bool) or completion < 0:
        return None
    return TokenUsage(prompt, completion)


def usage_from_json_tail(tail: bytes) -> TokenUsage | None:
    """The usage object near the end of a JSON reply (looking only at its last bytes)."""
    text = tail.decode("utf-8", errors="ignore")
    marker = text.rfind('"usage"')
    if marker == -1:
        return None
    colon = text.find(":", marker)
    if colon == -1:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[colon + 1 :].lstrip())
    except ValueError:
        return None
    return _from_object(value)


class JsonTail:
    """Keeps the last bytes of a reply that is being passed on, to read its usage afterwards."""

    def __init__(self) -> None:
        self._tail = b""

    def feed(self, chunk: bytes) -> None:
        """Remember the end of everything seen so far."""
        self._tail = (self._tail + chunk)[-_TAIL_BYTES:]

    def usage(self) -> TokenUsage | None:
        """The usage reported in the reply, if any."""
        return usage_from_json_tail(self._tail)


def wants_stream_usage(path: str, body: dict[str, Any]) -> bool | None:
    """Ask vLLM for usage on a streamed completion; say whether the client asked for it itself.

    Returns None when the request is not a stream we can add this to (the body is untouched).
    Otherwise returns True if the client already asked for usage, False if we just did, in
    which case the extra event must be hidden from the client (``SseUsage(strip=True)``).
    """
    if path not in _STREAMED_PATHS or body.get("stream") is not True:
        return None
    options = body.get("stream_options")
    if options is None:
        body["stream_options"] = {"include_usage": True}
        return False
    if not isinstance(options, dict):
        return None  # malformed: let vLLM answer with its own error
    if options.get("include_usage") is True:
        return True
    body["stream_options"] = {**options, "include_usage": True}
    return False


class SseUsage:
    """Passes a server-sent-events stream on, noting the usage it reports.

    With ``strip`` the final usage-only event (``"choices": []``) is held back, because the
    client did not ask for it and some clients choke on a chunk without choices.
    """

    def __init__(self, *, strip: bool) -> None:
        self._strip = strip
        self._buffer = b""
        self.usage: TokenUsage | None = None

    def feed(self, chunk: bytes) -> bytes:
        """Take a chunk of the stream, return what to send to the client now."""
        self._buffer += chunk
        events = self._buffer.replace(b"\r\n", b"\n").split(b"\n\n")
        self._buffer = events.pop()  # the last piece is an event that is not finished yet
        out = b""
        for event in events:
            if self._look(event) and self._strip and self._is_usage_only(event):
                continue
            out += event + b"\n\n"
        if len(self._buffer) > _MAX_EVENT_BYTES:  # absurdly large event: stop trying to parse it
            out += self._buffer
            self._buffer = b""
        return out if self._strip else chunk

    def finish(self) -> bytes:
        """What is left when the stream ends (hand it to the client as it is)."""
        rest, self._buffer = self._buffer, b""
        if rest.strip():
            self._look(rest)
        return rest if self._strip else b""

    def _look(self, event: bytes) -> bool:
        """Note usage in an event; True if it carried some."""
        if b'"usage"' not in event:
            return False
        for line in event.split(b"\n"):
            if not line.startswith(b"data:"):
                continue
            payload = line[5:].strip()
            if payload == b"[DONE]":
                continue
            try:
                found = _from_object(json.loads(payload).get("usage"))
            except (ValueError, AttributeError):
                continue
            if found is not None:
                self.usage = found
                return True
        return False

    @staticmethod
    def _is_usage_only(event: bytes) -> bool:
        for line in event.split(b"\n"):
            if line.startswith(b"data:"):
                try:
                    return bool(json.loads(line[5:].strip()).get("choices") == [])
                except (ValueError, AttributeError):
                    return False
        return False
