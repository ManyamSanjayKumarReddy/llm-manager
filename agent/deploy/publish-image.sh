#!/usr/bin/env bash
# Builds the agent image and pushes it to Docker Hub (or any registry).
#
#   docker login
#   agent/deploy/publish-image.sh yourhubuser/wakeful-agent
#
# Tags the image with the agent's version (from agent/pyproject.toml) and as "latest". Put the same
# name in the backend's AGENT_DOCKER_IMAGE setting (e.g. yourhubuser/wakeful-agent:latest) so the
# install command pulls it.
set -euo pipefail

repo="${1:?usage: publish-image.sh yourhubuser/wakeful-agent}"
here="$(cd "$(dirname "$0")/.." && pwd)"
version="$(sed -n 's/^version = "\(.*\)"/\1/p' "$here/pyproject.toml" | head -n 1)"
[ -n "$version" ] || { echo "could not read the version from pyproject.toml" >&2; exit 1; }

docker build -t "$repo:$version" -t "$repo:latest" "$here"
docker push "$repo:$version"
docker push "$repo:latest"
echo "Pushed $repo:$version and $repo:latest"
