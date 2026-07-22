#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

if [[ "${1:-}" == "--" ]]; then
	shift
else
	set -- /bin/bash
fi

DOCKER_TTY_ARGS=(-i)
if [[ -t 0 && -t 1 ]]; then
	DOCKER_TTY_ARGS=(-it)
fi

exec docker run --rm "${DOCKER_TTY_ARGS[@]}" \
	-v "${CODEX_WORKSPACE_ROOT}:${CODEX_ZEPHYR_XEN_CONTAINER_WORKSPACE}" \
	-w "${CODEX_ZEPHYR_XEN_CONTAINER_WORKSPACE}" \
	"${CODEX_ZEPHYR_XEN_IMAGE}" \
	"$@"
