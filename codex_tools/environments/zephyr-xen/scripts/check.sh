#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

if ! command -v docker >/dev/null 2>&1; then
	echo "docker is not installed or not on PATH"
	exit 1
fi

if ! docker image inspect "${CODEX_ZEPHYR_XEN_IMAGE}" >/dev/null 2>&1; then
	echo "missing Docker image: ${CODEX_ZEPHYR_XEN_IMAGE}"
	echo "build it with: ${SCRIPT_DIR}/build.sh"
	exit 1
fi

docker run --rm "${CODEX_ZEPHYR_XEN_IMAGE}" bash -lc '
set -euo pipefail
west --version
cmake --version | head -1
ninja --version
qemu-system-aarch64 --version | head -1
"${ZEPHYR_SDK_INSTALL_DIR}/gnu/aarch64-zephyr-elf/bin/aarch64-zephyr-elf-gcc" --version | head -1
python3 - <<'"'"'PY'"'"'
import clang.cindex
print("clang.cindex ok")
PY
'
