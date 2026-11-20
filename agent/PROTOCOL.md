# Outbound connection protocol

How a Wakeful agent and Wakeful talk when the agent connects out (`AGENT_CONNECT_URL`). Implemented
by `src/wakeful_agent/tunnel.py` (agent) and `backend/src/llm_manager/services/tunnel.py` (Wakeful).

## Connection

The agent opens a WebSocket to `wss://<wakeful>/api/agent/connect` with the header
`Authorization: Bearer <enrollment token>`. Wakeful stores only the token's SHA-256, finds the
server it belongs to, and accepts; an unknown or revoked token is refused with HTTP 403 before the
upgrade. One agent per server: a second connection with the same token closes the first with close
code **4000**. Revoking or replacing the token closes the connection with code 1008.

Every frame is a WebSocket **text** message holding one JSON object with a type `t`. Bodies are
base64 in `b`, in pieces of at most 256 KiB. Many calls share the connection; each has an integer
`id` chosen by Wakeful.

## Frames

| Direction | `t` | Fields | Meaning |
|---|---|---|---|
| agent → Wakeful | `hello` | `version` | sent once after connecting |
| Wakeful → agent | `req` | `id`, `target`, `port`, `method`, `path`, `headers` | starts a call |
| both | `data` | `id`, `b` | a piece of the request body (to the agent) or answer body (to Wakeful) |
| both | `end` | `id` | the request body is complete / the answer is complete |
| agent → Wakeful | `head` | `id`, `status`, `headers` | the answer's status line and headers |
| agent → Wakeful | `error` | `id`, `message` | the call failed; no further frames for that `id` |
| Wakeful → agent | `cancel` | `id` | stop this call (the caller gave up); no reply |

`headers` is a list of `[name, value]` pairs. `path` includes the query string.

A call is: `req`, zero or more `data`, `end` (request); then `head`, zero or more `data`, `end`
(answer) — or `error` instead of `head`/`end`. The agent starts working when it has the request's
`end`. If the connection drops, the agent stops every running call (closing its connection to
vLLM, so vLLM drops the request) and Wakeful fails every call that was waiting.

## Targets

* `target: "agent"` — the agent's own HTTP interface (`/containers`, `/host`, ...). The agent answers
  it with its own application and its own token; any `Authorization` header sent is ignored.
* `target: "vllm"` — relayed to `http://127.0.0.1:<port><path>`. The port must belong to a container
  this agent manages (its `wakeful.port` label) or be listed in `AGENT_RELAY_PORTS`; anything else
  is answered with `error`. The request's own headers (including vLLM's `Authorization`) are
  passed on, minus hop-by-hop ones, and the answer is streamed back as it is produced.

## Not covered

Flow control: frames are queued without a limit, which is fine for token streams but would not suit
bulk transfers. One Wakeful process holds the connections, so Wakeful must run as a single process
(or the connection must be pinned to one).
