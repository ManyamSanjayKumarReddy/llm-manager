# The Wakeful agent as a container. Build and publish with deploy/publish-image.sh.
#
# It is started by Wakeful's install script (see README.md): host networking so it reaches the vLLM
# containers on 127.0.0.1, the Docker socket so it can control them, and --gpus all so it can read
# the GPUs with nvidia-smi.

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.8.2 /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
# The agent drives the docker command line (a single static binary).
COPY --from=docker:28-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
LABEL org.opencontainers.image.title="Wakeful agent" \
      org.opencontainers.image.description="Lets Wakeful control the vLLM containers on this GPU server"
# Root, because Docker access is root-equivalent anyway; what the agent may do is limited in code.
# It listens on a socket inside the container, not on a port: Wakeful reaches it through the
# outbound connection (AGENT_CONNECT_URL), so nothing here is exposed.
CMD ["uvicorn", "wakeful_agent.main:app_from_env", "--factory", "--uds", "/tmp/wakeful-agent.sock", "--no-access-log"]
