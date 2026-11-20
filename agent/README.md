# Wakeful agent

A small service that runs on a GPU server and lets Wakeful start, stop, restart, create and remove
its vLLM containers, and read the server's GPU, memory and disk figures. It is optional: servers
without an agent work exactly as before.

There are two ways for Wakeful to reach the agent. Pick one per server.

**A. The agent connects out (recommended, and the only option behind a firewall).** The agent dials
Wakeful and keeps one WebSocket open; Wakeful sends its calls, and the users' requests to the
server's models, down it. The server needs no open port, no certificate and no web-server rule.

```
agent on GPU server ──outbound wss──> Wakeful      (Wakeful's calls travel back down it)
```

**B. Wakeful calls in.** For servers Wakeful can reach directly (your own machines).

```
Wakeful (opslocal) ──https + token──> Apache on the GPU server ──> agent (127.0.0.1:8050) ──> docker
```

## What it will and will not do

- Only containers carrying the label `wakeful.managed=true` are ever listed or changed. Every other
  container on the server is invisible to the agent, so a shared production box stays safe.
- Wakeful sends a structured description, never a command line. The agent checks every field and
  builds the `docker run` arguments itself (no shell). Secrets (the container's API key, the
  Hugging Face token) go through the docker process environment, never the argument list.
- Images must come from `AGENT_IMAGES` (default `vllm/vllm-openai` and `vllm-openai`, the patched
  build), the model cache must be inside `AGENT_CACHE_ROOTS`, ports are published on `127.0.0.1`
  only, and flags the agent sets itself (`--host`, `--port`, `--api-key`, `--trust-remote-code`,
  ...) cannot be repeated.
- It never pulls images. The image must already be on the server (`docker pull ...` or
  `scripts/vllm-abort-sleep`), otherwise creating answers "image is not on this server yet".
- Every action is recorded in Wakeful's audit trail.

## Install (on each GPU server, once)

```bash
# 1. the code (any folder; the unit below assumes /opt/wakeful-agent)
git clone <your repository URL> /opt/wakeful-agent
cd /opt/wakeful-agent/agent && uv sync

# 2. settings: a long random token (only if Wakeful calls in; see below), and where model files are kept
install -m 600 /dev/null /etc/wakeful-agent.env
cat >> /etc/wakeful-agent.env <<ENV
AGENT_TOKEN=$(openssl rand -hex 32)
AGENT_CACHE_ROOTS=/root/.cache
AGENT_IMAGES=vllm/vllm-openai,vllm-openai
ENV
grep AGENT_TOKEN /etc/wakeful-agent.env     # this is the token you give Wakeful

# 3. run it
mkdir -p /var/log/wakeful-agent
cp deploy/wakeful-agent.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now wakeful-agent

# 4. check (should print {"ok":true,"version":"0.1.0"})
curl -s http://127.0.0.1:8050/healthz
```

Then expose it through the web server that already terminates TLS for this machine: see
`deploy/apache-agent.conf.example`. Plain HTTP across the network is refused by Wakeful, because the
token would travel in clear.

## Connect it to Wakeful: the agent dials out (A)

In the dashboard open **Servers**, click *Connect agent* on the server, then *Create connection
token*. It shows two lines, once:

```
AGENT_CONNECT_URL=wss://wakeful.example.com/api/agent/connect
AGENT_CONNECT_TOKEN=wkt_...
```

On the GPU server put them in `/etc/wakeful-agent.env` (`AGENT_TOKEN` is then not needed: nobody can
call the agent over HTTP), then `systemctl enable --now wakeful-agent`. The dialog shows when it
connects. The agent reconnects by itself after any interruption.

* Models registered on that server use the address **as seen from that server**, for example
  `http://127.0.0.1:8025`. Wakeful reaches it through the agent.
* Containers that were *not* created by Wakeful are only reachable if their port is listed in
  `AGENT_RELAY_PORTS` (comma-separated). Containers created from the dashboard are allowed
  automatically.
* *New token* disconnects the agent that uses the old one; *Disconnect* cuts the server off.
* Wakeful's own web server must pass WebSockets on `/api/agent/connect`: see
  `deploy/apache-wakeful-connect.conf.example`. Run Wakeful as a single process (the connections
  live in its memory).
* The wire format is in [PROTOCOL.md](PROTOCOL.md).

## Connect it to Wakeful: Wakeful calls in (B)

Dashboard → **Servers** → *Set up agent* on that server: enter the address (for example
`https://llm-demo.example.com/agent`) and the token. The row then shows the machine's free RAM and
GPU memory, and a **Containers** button.

From **Models → Add model** the last step then offers *Create and register*: the agent creates the
container with sleep mode on, and Wakeful registers it. The new container loads for a few minutes
(shown as down), then Wakeful puts it to sleep until a request arrives.

Rules Wakeful adds on top:

- A container that backs a registered model is only stopped or restarted while that model has no
  running or waiting request.
- Removing a container that backs a model also removes the model, and the dashboard asks you to type
  the container's name first.
- The link between a model and its container is the *Container* field in the model's settings. It is
  filled in automatically when the container is created from Wakeful; for older models, pick the
  container there (or Wakeful guesses from a port in the model's address).

## Settings (environment, prefix `AGENT_`)

| Variable | Meaning |
|---|---|
| `AGENT_TOKEN` | at least 32 characters; needed for mode B, optional for mode A |
| `AGENT_CONNECT_URL` | `wss://` address of Wakeful's `/api/agent/connect` (mode A) |
| `AGENT_CONNECT_TOKEN` | the connection token the dashboard showed (mode A) |
| `AGENT_RELAY_PORTS` | ports of vLLM containers not created by the agent that Wakeful may reach (mode A) |
| `AGENT_CACHE_ROOTS` | comma-separated folders a container may mount (default `~/.cache`) |
| `AGENT_IMAGES` | comma-separated allowed image repositories |
| `AGENT_DOCKER_BIN` | docker command (default `docker`) |
| `AGENT_NVIDIA_SMI_BIN` | nvidia-smi command (default `nvidia-smi`) |
| `AGENT_COMMAND_TIMEOUT_S` | longest one docker command may take (default 60) |

## Rotate the token

Change `AGENT_TOKEN` in `/etc/wakeful-agent.env`, `systemctl restart wakeful-agent`, then paste the
new token under *Servers → Settings* in the dashboard.

## Troubleshooting

| Symptom in the dashboard | Cause |
|---|---|
| "Agent not reachable" (mode B) | the service is down, or the web server rule is missing: `curl https://<host>/agent/healthz` |
| "Not connected" (mode A) | the service is down, or cannot reach Wakeful: `journalctl -u wakeful-agent` or `/var/log/wakeful-agent/agent.log` shows why |
| log: "Wakeful refused the connection (HTTP 403)" | the token is wrong or was revoked: create a new one |
| log: "another agent connected with this token" | the agent runs twice with the same token |
| "port N is not one of this agent's containers" | list the port in `AGENT_RELAY_PORTS` |
| "the agent ... refused the token" | the token differs from `AGENT_TOKEN` on that machine |
| "image ... is not on this server yet" | `docker pull` the image there first |
| "cache folder: must be inside ..." | add the folder to `AGENT_CACHE_ROOTS` |
| "image: only these repositories ..." | add the repository to `AGENT_IMAGES` |

## Develop

```bash
uv sync
uv run pytest && uv run ruff check . && uv run mypy
```

`tests/test_cli_docker.py` runs against the real Docker on your machine (one uniquely named test
container, never anything else) and is skipped when Docker or the `nginx:stable` image is missing.
`tests/golden_commands.json` is shared with the dashboard's tests: both must produce the same
`docker run` arguments.
