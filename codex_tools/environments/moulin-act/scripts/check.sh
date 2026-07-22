#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

if ! command -v docker >/dev/null 2>&1; then
	echo "docker is not installed or not on PATH"
	exit 1
fi

act_bin="${ACT_BIN:-}"
if [ -z "${act_bin}" ]; then
	if command -v act >/dev/null 2>&1; then
		act_bin=act
	elif [ -x /tmp/act-bin/act ]; then
		act_bin=/tmp/act-bin/act
	else
		echo "act is not installed; set ACT_BIN or put act in PATH"
		exit 1
	fi
fi

if ! docker image inspect "${CODEX_MOULIN_ACT_IMAGE}" >/dev/null 2>&1; then
	echo "missing Docker image: ${CODEX_MOULIN_ACT_IMAGE}"
	echo "build it with: ${SCRIPT_DIR}/build.sh"
	exit 1
fi

docker run --rm "${CODEX_MOULIN_ACT_IMAGE}" bash -lc '
set -euo pipefail
git --version
python3 --version
make --version | head -1
'

"${act_bin}" --version
