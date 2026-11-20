#!/usr/bin/env bash
# Installs the Wakeful agent on this GPU server. Run it as root:
#
#   curl -fsSL __WAKEFUL_URL__/install-agent.sh | sudo bash -s -- wkt_YOUR_TOKEN
#
# The agent runs as a Docker container that connects OUT to Wakeful: this server needs no open
# port, no certificate and no web-server rule. Running the command again updates the agent (the
# token is remembered); `--remove` takes it away again.
set -euo pipefail

CONNECT_URL="__CONNECT_URL__"
IMAGE="${WAKEFUL_AGENT_IMAGE:-__AGENT_IMAGE__}"
# The vLLM image models run in (the build that aborts requests when a model is put to sleep). It is
# the only one the agent may start here, and it is downloaded once now so the first model starts fast.
VLLM_IMAGE="${WAKEFUL_VLLM_IMAGE:-__VLLM_IMAGE__}"
ALLOWED_IMAGES="${VLLM_IMAGE%:*},vllm-openai"
NAME="wakeful-agent"
CONF_DIR="/etc/wakeful-agent"
ENV_FILE="$CONF_DIR/agent.env"
WAIT_S=40

say() { printf '%s\n' "$*"; }
warn() { printf 'Warning: %s\n' "$*" >&2; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<USAGE
Wakeful agent installer

  install-agent.sh [wkt_TOKEN] [options]

  wkt_TOKEN            the connection token the Wakeful dashboard showed (not needed again when
                       updating: it is remembered in $ENV_FILE)
  --cache DIR[,DIR]    folders where model files live and containers may mount (default: the
                       ~/.cache of the sudo user and of root)
  --relay-ports P,P    ports of vLLM containers that Wakeful did not create but should reach
  --no-download        do not download the vLLM image now (it is downloaded when a model is created)
  --remove             stop and remove the agent and its saved settings
  -h, --help           this text
USAGE
}

token="" cache="" relay="" remove=0 prefetch=1
while [ $# -gt 0 ]; do
  case "$1" in
    wkt_*) token="$1" ;;
    --cache) [ $# -ge 2 ] || die "--cache needs a folder"; cache="$2"; shift ;;
    --relay-ports) [ $# -ge 2 ] || die "--relay-ports needs a list of ports"; relay="$2"; shift ;;
    --no-download) prefetch=0 ;;
    --remove) remove=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown argument: $1" ;;
  esac
  shift
done

[ "$(id -u)" -eq 0 ] || die "run this as root: put 'sudo' before 'bash'"
command -v docker >/dev/null 2>&1 || die "Docker is not installed on this server (https://docs.docker.com/engine/install/)"
docker info >/dev/null 2>&1 || die "Docker is installed but not running (try: systemctl start docker)"

if [ "$remove" -eq 1 ]; then
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$CONF_DIR"
  say "The Wakeful agent is removed. Your vLLM containers were not touched."
  say "Also delete this server's connection in the Wakeful dashboard (Servers > Connect agent > Disconnect)."
  exit 0
fi

saved() { [ -f "$ENV_FILE" ] && sed -n "s/^$1=//p" "$ENV_FILE" | head -n 1 || true; }

[ -n "$token" ] || token="$(saved AGENT_CONNECT_TOKEN)"
[ -n "$token" ] || { usage >&2; die "give the connection token from the Wakeful dashboard (Servers > Connect agent)"; }
grep -Eq '^wkt_[A-Za-z0-9_-]{32,}$' <<<"$token" || die "that does not look like a Wakeful token (it starts with wkt_)"

# Folders the agent may let containers mount: the model cache.
if [ -z "$cache" ]; then
  cache="$(saved AGENT_CACHE_ROOTS)"
fi
if [ -z "$cache" ]; then
  cache="/root/.cache"
  if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ]; then
    home="$(getent passwd "$SUDO_USER" | cut -d: -f6 || true)"
    [ -n "$home" ] && [ -d "$home" ] && cache="$home/.cache,$cache"
  fi
fi
[ -n "$relay" ] || relay="$(saved AGENT_RELAY_PORTS)"
grep -Eq '^([0-9]+(,[0-9]+)*)?$' <<<"$relay" || die "--relay-ports: numbers separated by commas, for example 8025,8026"

mounts=()
IFS=',' read -r -a folders <<<"$cache"
for folder in "${folders[@]}"; do
  case "$folder" in
    /*) ;;
    *) die "--cache: '$folder' is not an absolute path" ;;
  esac
  case "$folder" in
    *[[:space:]:]*) die "--cache: '$folder' must not contain spaces or colons" ;;
  esac
  mkdir -p "$folder"
  mounts+=(-v "$folder:$folder")
done

gpu=()
runtimes="$(docker info --format '{{json .Runtimes}}' 2>/dev/null || true)"
if [[ "$runtimes" == *nvidia* ]]; then
  gpu=(--gpus all)
else
  warn "Docker has no NVIDIA runtime here (install the NVIDIA Container Toolkit): the agent will not see this server's GPUs, and Wakeful cannot create containers on it."
fi

say "Pulling $IMAGE ..."
if ! docker pull "$IMAGE" >/dev/null 2>&1; then
  docker image inspect "$IMAGE" >/dev/null 2>&1 || die "could not download $IMAGE (is the name right, and is this server online?)"
  warn "could not download $IMAGE; using the copy already on this server."
fi

umask 077
mkdir -p "$CONF_DIR"
{
  printf 'AGENT_CONNECT_URL=%s\n' "$CONNECT_URL"
  printf 'AGENT_CONNECT_TOKEN=%s\n' "$token"
  printf 'AGENT_CACHE_ROOTS=%s\n' "$cache"
  printf 'AGENT_IMAGES=%s\n' "$ALLOWED_IMAGES"
  [ -z "$relay" ] || printf 'AGENT_RELAY_PORTS=%s\n' "$relay"
} >"$ENV_FILE"
chmod 600 "$ENV_FILE"

docker rm -f "$NAME" >/dev/null 2>&1 || true
# Host networking: the agent reaches the vLLM containers on 127.0.0.1, as Wakeful expects.
# The Docker socket is how it starts and stops containers (that is root-equivalent, so the agent
# only does what its code allows: labelled containers, allowlisted images, the cache folders).
docker run -d --name "$NAME" --restart unless-stopped --network host \
  --env-file "$ENV_FILE" \
  --security-opt no-new-privileges --cap-drop ALL \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ${mounts[@]+"${mounts[@]}"} ${gpu[@]+"${gpu[@]}"} \
  "$IMAGE" >/dev/null

say "Waiting for the agent to reach Wakeful ..."
for _ in $(seq "$WAIT_S"); do
  logs="$(docker logs "$NAME" 2>&1 || true)"
  if grep -q "connected to Wakeful" <<<"$logs"; then
    say ""
    say "Connected: this server can now be managed from Wakeful ($CONNECT_URL)."
    if [ "$prefetch" -eq 1 ]; then
      say "Downloading the vLLM image $VLLM_IMAGE (several GB, only the first time) ..."
      if ! docker pull "$VLLM_IMAGE"; then
        warn "could not download $VLLM_IMAGE now; Wakeful will try again when you create a model."
      fi
    fi
    say ""
    say "Done. Go back to the dashboard: it shows 'Connected' and you can add models."
    say "Logs: docker logs -f $NAME      Update: run this command again      Remove: add --remove"
    exit 0
  fi
  if grep -q "refused the connection" <<<"$logs"; then
    docker logs --tail 5 "$NAME" >&2 || true
    docker rm -f "$NAME" >/dev/null 2>&1 || true
    die "Wakeful refused the token: copy it again from the dashboard, or create a new one (Servers > Connect agent > New token)."
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" != "true" ] \
    || [ "$(docker inspect -f '{{.RestartCount}}' "$NAME" 2>/dev/null)" != "0" ]; then
    docker logs --tail 15 "$NAME" >&2 || true
    die "the agent keeps stopping right after it starts (see the lines above)."
  fi
  sleep 1
done
docker logs --tail 10 "$NAME" >&2 || true
die "the agent is running but could not reach $CONNECT_URL within ${WAIT_S}s (see the lines above). Is this server online, and is outbound HTTPS allowed?"
