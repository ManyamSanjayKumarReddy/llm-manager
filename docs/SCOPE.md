# Wakeful: scope document

Status as of 2026-11-26. Covers `main` at `e695e44`. The branches `dev`, `feature/container-agent` and `feature/agent-outbound` are all fully contained in `main`; nothing is waiting on another branch.

---

## 1. What it is

**Wakeful is a self-hosted router for GPU language models. Models sleep when nobody uses them and wake in about a second when a request arrives.**

Programs call one OpenAI-compatible address with an API key. Behind it sit vLLM containers on one or many GPU servers. When a model is idle, its weights move from GPU memory to CPU memory (vLLM "sleep mode"), so the GPU is nearly empty and another model can use it. A request for a sleeping model wakes it and waits, so the caller sees a slightly slower first answer and nothing else.

```
programs ──(API key)──┐
                      ├─> Wakeful (FastAPI, TLS) ──> vLLM containers (sleep mode)
browser ──(sign-in)───┘        │                          ▲
                               ├─ PostgreSQL              │ calls + users' requests
                               └─ WebSocket <── agent on each GPU server (dials out)
```

Three parts:

| Part | What it is |
|---|---|
| **Router** (`backend/`) | FastAPI + PostgreSQL. The OpenAI-compatible `/v1` endpoint, the scheduler that decides which model owns a GPU, API keys, users, usage, audit. |
| **Dashboard** (`web/`) | React + TypeScript. Overview, Servers, Models, Usage, History, Connect, Users, Scheduling, Audit, Account, plus a public landing page. |
| **Agent** (`agent/`) | A small Docker container on each GPU server. Starts, stops, creates and removes that server's vLLM containers and reports its GPU, RAM and disk. It connects *out* to Wakeful, so the GPU server needs no open port. |

---

## 2. The problem it solves

GPU memory is the expensive, scarce part of running your own models. The usual choices are all bad:

1. **Keep every model loaded.** You need one GPU per model, and most of them sit idle most of the day.
2. **Unload and reload on demand.** Frees the GPU, but a cold start (reading weights from disk, building the engine) takes tens of seconds to minutes. Users see timeouts.
3. **Rent hosted APIs.** No GPU management, but prompts leave your network, cost scales with tokens, and you cannot run your own fine-tunes or private models.

Wakeful gives a fourth option: many models share few GPUs, each one costs almost nothing while asleep, and waking takes about a second. Measured: gpt-oss-20b on an RTX 4090 used 17.7 GB awake and 1.3 GB asleep; wake took 0.75 s, sleep 1.55 s.

---

## 3. Who it is for and where it fits

- **Teams with their own GPU servers** (on-prem, colocation, rented cloud boxes) who run several models and cannot dedicate a GPU to each. This is the original case: two shared production servers running Qwen3-VL-8B, Qwen2.5-7B and gpt-oss-20b.
- **Organisations that cannot send prompts to a third party** (privacy, compliance, customer data). Wakeful never stores prompts or answers.
- **Service providers who will host models for clients** on the clients' own hardware (the outbound agent was built for this; multi-tenancy is the missing piece, see section 7).
- **Shared GPUs.** A GPU that also runs training or other jobs can be left almost empty when the models are idle.

Where it runs: one Linux host for Wakeful (Python 3.12+, PostgreSQL in Docker, any reverse proxy such as nginx), plus Docker and the NVIDIA Container Toolkit on each GPU server.

---

## 4. Feature list (what is built)

### 4.1 One OpenAI-compatible endpoint
- `/v1/chat/completions`, `/v1/completions`, `/v1/embeddings` and any other `/v1/*` path are passed through to the model named in the request body; `/v1/models` lists the models a key may use.
- Streaming responses pass straight through.
- Token counts are read from the answer (and requested for streams) so usage is recorded without storing any text.
- Errors follow HTTP meaning: `401` bad key, `403` model not allowed, `404` unknown model, `429` over the rate limit, `503` + `Retry-After` for a model that could not wake, a wait past the queue timeout, or a request stopped for a higher-priority model.
- Existing OpenAI SDKs work by changing the base URL.

### 4.2 GPU scheduler (`engine/manager.py`)
- **Wake on demand.** A request for a sleeping model wakes it and waits.
- **Shared GPUs without clashes.** Models are placed on a *server + GPU number*. Models on the same GPU are never awake together. A request for the sleeping one waits while the awake one finishes its running requests, is put to sleep, and then the target wakes. A model is never put to sleep while it has requests running.
- **Fair turns.** Equal priorities take turns (turn length, default 10 s).
- **Priorities.** When models sharing a GPU both have requests waiting, the higher number goes first. A lower-priority model never interrupts a higher one that is serving or served within the priority hold.
- **Per-model idle timeout.** Each model sleeps after its own idle minutes.
- **Optional preemption (off by default).** After N seconds of waiting, a high-priority request stops a *strictly lower-priority* model's running requests (they get `503` + `Retry-After`, streams end with an error event) and takes the GPU. Safe on vLLM 0.17+ and on the patched 0.10.1 image; on stock older vLLM, Wakeful refuses unless it can prove the engine is idle, because freeing a GPU under a live request crashes the vLLM engine.
- **Self-healing.** A reaper re-checks every model each second or so, marks stopped containers as down, adopts a model when its container comes back, and tolerates one missed health check.
- **Admin-editable timings**, stored in the database and applied live: queue timeout, turn length, priority hold, preemption time, wake/sleep limits, reaper interval, sleep level.
- **Startup does not block.** Requests wait for the startup check instead of failing.

### 4.3 Servers and fleet
- Register GPU servers (name, GPU count, GPU type). A GPU is *server + number*, so GPU 0 on two servers are different GPUs.
- Models are placed on a server and one or more GPUs (tensor parallel across several).
- Dashboard shows each server's GPU, memory and disk load when its agent is connected.

### 4.4 The agent: containers from the browser (admin only)
- **Start, stop, restart, read logs, create and remove** vLLM containers on a GPU server, without SSH.
- **Create and register**: the dashboard builds the container from a structured spec and registers the model in one step. The agent downloads the vLLM image itself if it is missing (allowlisted repositories only) and removes a half-made container if `docker run` fails.
- **Safe by construction.** The agent only ever sees containers carrying its own label, so a shared production box stays safe. Wakeful sends a structured spec, never a command line; the agent validates every field and builds the arguments itself (no shell). Images come from an allowlist, model caches must sit inside allowed folders, ports bind to `127.0.0.1`, and secrets (container API key, Hugging Face token) travel in the process environment, never the argument list.
- **Removing a container removes its model**, behind a type-the-name danger confirmation. Every action is audited.
- **"Starting" vs "down, and why".** For models linked to a container, Wakeful reads the container state and its log and says in plain words why a model is not ready (still loading, not enough free GPU memory, and so on).

### 4.5 No open ports: the agent connects out
- The agent dials Wakeful over a WebSocket (`wss`) and keeps it open. Wakeful sends its management calls **and the users' inference traffic** down that connection, so the GPU server needs no inbound port, certificate, DNS name or firewall rule and can sit behind NAT.
- Each server gets its own enrollment token (`wkt_...`, shown once, stored only as a SHA-256). Revoking it closes the connection; a second connection with the same token replaces the first.
- Wire format is documented in `agent/PROTOCOL.md`.
- Servers Wakeful can reach directly can use the older call-in mode instead (HTTPS + token).

### 4.6 One-command install
- From the dashboard: *Servers → Connect agent* shows a command such as `curl -fsSL https://<wakeful>/install-agent.sh | sudo bash -s -- wkt_...`.
- The script checks Docker, downloads the agent image, starts it with `--restart unless-stopped`, saves the token in a root-only file, pre-downloads the vLLM image, and waits until the dashboard shows the server as connected. Re-running it updates; `--remove` uninstalls.

### 4.7 Patched vLLM image (`scripts/vllm-abort-sleep`)
- vLLM 0.10.1's `/sleep` does not abort running requests, and freeing the GPU under one crashes the engine. Newer vLLM fixes this, but 0.17+ needs a newer NVIDIA driver than many servers have (driver 570 fails with error 804).
- Wakeful ships a build recipe for a 0.10.1 image whose `/sleep` aborts running requests first, which makes preemption safe on older drivers. It is published on Docker Hub and is the dashboard's default image.

### 4.8 API keys and access control
- Keys for programs: shown once, stored hashed, optional **model allow-list**, optional **per-minute request limit**, revocable instantly, last-used time.
- Cookies never work on `/v1`; keys never work on `/api`.
- Users with roles `admin` and `viewer`. No default account; the first admin is created from the command line and nobody can sign up. The last admin cannot be removed.

### 4.9 Observability
- **Overview:** live state of every model grouped by server (asleep, waking, awake, busy, starting, down with the reason), queue and running counts.
- **History:** requests, errors, median and p95 latency, queue wait, and every wake, sleep, swap and preemption, per model and time window, including how an engine was proven idle.
- **Usage:** requests and tokens per API key, model and day (kept two years by default).
- **Audit:** every administrative change (who, what, from which IP), kept a year by default.
- **Connect page:** the base URL, API key and model names a developer needs, as plain tables.

### 4.10 Security
- argon2id passwords (12+ characters), lockout after 5 wrong attempts, per-IP sign-in limit.
- Session token stored only as a SHA-256; `__Host-` cookie that is `HttpOnly`, `Secure`, `SameSite=Strict`; CSRF header and same-origin check on every change; strict Content-Security-Policy, HSTS, no framing.
- Container API keys are write-only: stored, never returned, logged or audited.
- Prompts and answers are never stored.
- Proprietary licence, all rights reserved.

### 4.11 Operations
- Settings by environment variable or admin page; PostgreSQL schema managed by Aerich migrations (8 so far); health endpoint `/healthz`; CLI for `create-user`, `list-users`, `reset-password`, `unlock-user`, `create-api-key`.
- Example nginx and Apache configs for the agent's WebSocket path; systemd unit for the call-in agent.
- Quality gates: ruff, mypy `--strict`, eslint, tsc. Test suites at last count: backend 274, agent 115, dashboard 139 (backend tests run against a real PostgreSQL in Docker; the agent has real-Docker tests).

---

## 5. How it compares

Based on general knowledge of these products, not a fresh hands-on comparison. Check current versions before using this table outside the company.

| | Wakeful | Ollama | llama-swap | LiteLLM / API gateways | vLLM production-stack, KServe, Ray Serve | Serverless GPU (RunPod, Modal, Baseten) | Hosted APIs (OpenAI etc.) |
|---|---|---|---|---|---|---|---|
| Frees GPU when idle | Yes, weights kept in CPU RAM | Yes, unloads | Yes, kills process | No (does not manage GPUs) | Scale to zero in Kubernetes | Yes, scale to zero | Not your concern |
| Time back from idle | **about 1 s** | reload from disk | restart the server process | n/a | typically tens of seconds to minutes | typically tens of seconds to minutes | none |
| Engine | vLLM (batching, high throughput) | llama.cpp based | any, mainly llama.cpp/vLLM | any | vLLM and others | any | provider's |
| Several models on one GPU, with priority and preemption | **Yes** | Limited, no priorities | Swap only, no priorities | No | Not as a built-in scheduler | Not applicable | Not applicable |
| Many GPU servers behind one endpoint | **Yes** | One machine | One machine | Routes to URLs only | Yes, inside one Kubernetes cluster | Provider's fleet | Provider's fleet |
| Servers reachable only by dialling out (NAT, firewall) | **Yes, no open ports** | No | No | No | No (needs cluster networking) | Not applicable | Not applicable |
| Create and manage containers from a web dashboard | **Yes** | No | No | No | Needs Kubernetes skills | Provider console | Not applicable |
| One-command server install | **Yes** | Yes (install script) | Binary | Docker/pip | Helm | Not applicable | Not applicable |
| Needs Kubernetes | **No** | No | No | No | Yes | No | No |
| Keys, per-key limits, model allow-list, usage | **Yes** | No | Basic | Yes (richer: budgets, many providers) | Not built in | Provider's | Yes |
| Data stays on your hardware | **Yes** | Yes | Yes | Depends | Yes | No | No |

**What is genuinely different (the pitch):**

1. **Sleep, not unload.** Competing "swap on demand" tools throw the model away and reload it. Wakeful keeps the weights in CPU memory and puts them back on the GPU, so the first answer after idle is about a second slower, not half a minute. This also removes the main reason people give each model its own GPU.
2. **A GPU scheduler with opinions.** Priorities, turn length, priority hold, "never interrupt a running answer unless you opted in", and a provable-idle rule before stopping a request. Most gateways and swap proxies have none of this.
3. **No open ports, one command.** An agent that dials out and carries both management and inference traffic is rare in self-hosted LLM tooling. It is what lets Wakeful run for *someone else's* GPU servers.
4. **A control plane without Kubernetes.** Create, start, stop, log and remove containers from the browser, with host GPU/RAM/disk and plain-language failure reasons, on plain Docker.
5. **Works on the hardware people actually have.** The patched vLLM image makes safe preemption possible on servers whose NVIDIA driver cannot run vLLM 0.17+.
6. **Private by design.** No prompt or answer is ever stored.

**What others do better today (be honest in sales conversations):**

- LiteLLM and similar gateways support dozens of providers, budgets and spend limits; Wakeful serves only its own vLLM models.
- Kubernetes stacks scale one model across many replicas and add GPUs automatically; Wakeful does not autoscale or load-balance replicas.
- Ollama and llama.cpp tooling run on laptops, CPUs and Apple silicon; Wakeful is NVIDIA + vLLM only.
- Hosted APIs need no hardware and have frontier models.

---

## 6. Honest limits

- **CPU RAM is the capacity limit.** A sleeping model keeps its weights in RAM. On the shared 61 GiB server, one sleeping model cost about 17 GiB plus about 11 GiB container overhead, so only one more fits. Plan RAM per GPU server before adding models.
- **vLLM only**, and it must have sleep mode (the 0.10.1 patched image is the supported default).
- **Wakeful must run as a single process** (the agent connections live in memory).
- **Not yet verified:** the agent has never run with the NVIDIA runtime on the production servers (rehearsed on a cloud box only); the wake time of larger models and slower RAM has not been measured; sleep with every GPU type is not verified (checked on RTX 4090, RTX PRO 4500 Blackwell, two 5060 Ti and two 4060 Ti servers).
- Agent protocol has no flow control and bad enrollment tokens are not rate limited; the call-in agent token is stored as plain text in the database.
- Only per-minute request limits; no token budgets or billing.

---

## 7. Not in scope yet (candidate next phase)

| Item | Why it matters |
|---|---|
| **Multi-tenancy**: clients with their own servers, models, keys, users and audit trail; enrollment tokens that belong to a client | Required before offering Wakeful to outside clients. Explicitly deferred. |
| Run more than one Wakeful process / high availability | Removes the single-process limit. |
| Token budgets, spend limits, billing export | Needed for charging clients. |
| Replicas of one model across servers, load balancing | Throughput beyond one GPU set. |
| Show each model's vLLM version and a "patched" badge | Operational clarity. |
| Capacity planner (RAM per server vs sleeping models) | Prevents the RAM limit being hit by surprise. |
| Move to vLLM 0.17+ when drivers allow | Drops the patched image. |
| Flow control and token-attempt rate limit on the agent link | Hardening before public use. |

Open housekeeping from earlier work: republish the agent image after the latest agent changes, deploy `e578535` and `e695e44` to the production server, re-run the install command on the cloud test box, rotate the container API key and Hugging Face token that were pasted earlier, and remove the old `qwen2.5-7b-official` container.

---

## 8. Delivery history (how it was built)

| Phase | What shipped |
|---|---|
| 1. Core | Router, scheduler, dashboard, API keys, users, audit, history (`5f426d8`) |
| 2. Preemption | Optional stop of lower-priority running requests (`39a6067`) |
| 3. Fleet | Servers, usage per key/model/day, Connect page, editable scheduler timings |
| 4. Hardening | Safe preemption on old vLLM, patched image, faster down-detection |
| 5. Container control | Agent, backend routes, dashboard dialogs, runbook (`6f0de4d` to `ead0bf7`) |
| 6. Outbound agent | WebSocket tunnel, tokens, one-command install, nginx example (`e781601` to `26849de`) |
| 7. Polish | Image auto-download, "starting / down because", dashboard grouped by server (`e578535`, `e695e44`) |
