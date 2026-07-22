#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

docker run --rm --network "${CODEX_DOCKER_BUILD_NETWORK}" \
	ubuntu:24.04 getent hosts archive.ubuntu.com >/dev/null

docker build \
	--network "${CODEX_DOCKER_BUILD_NETWORK}" \
	-t "${CODEX_ZEPHYR_XEN_IMAGE}" \
	"${CODEX_ENV_DIR}"
