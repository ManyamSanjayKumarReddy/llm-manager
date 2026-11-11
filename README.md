# Wakeful

Models that wake when you call. One OpenAI-compatible endpoint in front of vLLM containers that share GPUs:
idle models sleep (weights move to CPU memory, the GPU is nearly empty) and wake in about a second when a request arrives.
A password-protected dashboard registers models, manages people and API keys, and shows history.

```
programs ──(API key)──┐
                      ├─> Wakeful (FastAPI, TLS) ──> vLLM containers (sleep mode, localhost)
browser ──(sign-in)───┘        └─ PostgreSQL (Docker)
```

| Folder | |
|---|---|
| `backend/` | FastAPI, Tortoise ORM, Pydantic, Aerich, uv |
| `web/` | Dashboard and landing page: React + TypeScript + Vite (built to `web/dist`, served by the backend) |
| `scripts/` | `make-cert.sh` (self-signed certificate), `bootstrap.sh` (start model containers one at a time) |

## Scheduling

- Models that share a GPU are never awake together. A request for a sleeping model waits while the other finishes
  its running requests and sleeps, then the target wakes.
- A model is never put to sleep while it has requests running. Equal priorities take turns (`MIN_AWAKE_S`).
- **Priority:** when models sharing a GPU both have requests waiting, the higher number goes first. A lower-priority
  model never interrupts a higher one that is serving or served within `PRIORITY_HOLD_S`.
- Every model sleeps after its own idle time, whatever its priority.
- Failure to wake or a wait over `QUEUE_TIMEOUT_S` gives `503` + `Retry-After`; unknown model `404`, not allowed `403`,
  bad key `401`, over the rate limit `429`.

Wakeful does not create models or touch Docker. You start vLLM containers; the dashboard builds the command and registers them.

## Run

Needs Docker (PostgreSQL only), [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
# 1. database (local only); choose a password
docker run -d --name llm-manager-db --restart unless-stopped \
  -e POSTGRES_USER=llm_manager -e POSTGRES_DB=llm_manager -e POSTGRES_PASSWORD='<password>' \
  -p 127.0.0.1:5432:5432 -v llm_manager_pgdata:/var/lib/postgresql/data postgres:16-alpine

# 2. settings: copy .env.example to .env and put the same password in DATABASE_URL
cp .env.example .env

# 3. backend
cd backend && uv sync
uv run aerich upgrade
uv run llm-manager create-user --username you --role admin    # first admin; nobody can sign up

# 4. dashboard
cd ../web && npm ci && npm run build

# 5. start (self-signed certificate, or put your own in certs/)
cd .. && scripts/make-cert.sh <hostname>
cd backend && uv run uvicorn llm_manager.main:app_from_env --factory --host 0.0.0.0 --port 8000 \
  --ssl-keyfile ../certs/privkey.pem --ssl-certfile ../certs/fullchain.pem
```

Plain-HTTP development only: set `COOKIE_SECURE=false` and drop the two `--ssl-*` flags.

Then open `https://<host>:8000`, sign in, and use **Models → Add model**. The popup builds the `docker run` command
(sleep mode on), then registers the container. Containers start awake, so start them one at a time and put each to sleep:
`scripts/bootstrap.sh gpt-oss-20b:8025`.

Call it with any OpenAI client:

```bash
curl https://<host>:8000/v1/chat/completions -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"model": "gpt-oss-20b", "messages": [{"role": "user", "content": "Hello"}]}'
```

CLI (from `backend/`): `uv run llm-manager list-users | reset-password | unlock-user | create-api-key`.

## Security

- No default account. argon2id passwords (12+ characters), lockout after 5 wrong attempts, per-IP sign-in limit.
- Sessions: random token (SHA-256 stored), `__Host-` cookie that is `HttpOnly`, `Secure`, `SameSite=Strict`; CSRF header and
  same-origin check on every change; strict Content-Security-Policy, HSTS, no framing.
- API keys for programs: shown once, stored hashed, model allow-list, per-minute limit, revocable. Cookies don't work on `/v1`; keys don't work on `/api`.
- A container's own API key is stored in the database (needed to call it). It is never returned by the API, logged, or audited.
  Skip it if the container is bound to `127.0.0.1`, which the generated command does.
- Roles `admin` and `viewer`; the last admin can't be removed; every change is audited. Prompts and answers are never stored.
- vLLM's `/sleep` and `/wake_up` have no password: keep the containers on `127.0.0.1`.

## Develop

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest   # pytest starts a PostgreSQL in Docker
cd web && npm run lint && npm run typecheck && npm test && npm run build
cd web && npm run dev        # hot reload; needs the backend on :8000 and ALLOWED_ORIGINS=http://127.0.0.1:5173 in .env
```

Database changes: edit `backend/src/llm_manager/db/models.py`, run `uv run aerich migrate --name <what>`, commit the new file in `backend/migrations/models/`.
Settings are listed in `.env.example`.

## Not verified on real hardware yet

Sleep mode with tensor parallelism 2 and Blackwell (RTX 5060 Ti) GPUs; Qwen3-VL-8B (needs a newer vLLM image);
`--gpu-memory-utilization` tuning. The cloud test (one Ada GPU) measured a 0.75 s wake and about 1.3 GB used while asleep.

## Notes

Stickers come from [`stick-it-up`](https://www.npmjs.com/package/stick-it-up) (free for non-commercial use; check it suits you
or remove `web/src/components/Stickers.tsx`). Fonts are self-hosted via `@fontsource`. No license file is included yet.
