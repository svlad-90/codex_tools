#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

if ! docker image inspect "${CODEX_MOULIN_ACT_IMAGE}" >/dev/null 2>&1; then
	echo "missing Docker image: ${CODEX_MOULIN_ACT_IMAGE}"
	echo "build it with: ${SCRIPT_DIR}/build.sh"
	exit 1
fi

exec docker run --rm -it \
	-v "${CODEX_WORKSPACE_ROOT}:${CODEX_WORKSPACE_ROOT}" \
	-w "${CODEX_WORKSPACE_ROOT}" \
	"${CODEX_MOULIN_ACT_IMAGE}" "$@"
