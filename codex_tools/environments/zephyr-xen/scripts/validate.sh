#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

usage() {
	cat <<'EOF'
Usage:
  validate.sh --zephyr <workspace-relative-zephyr-repo> \
              --app <app-path-relative-to-zephyr> \
              --board <board> \
              --build-dir <build-dir-relative-to-zephyr> \
              [--cmake-arg <arg>]...
EOF
}

ZEPHYR_REPO=""
APP_PATH=""
BOARD=""
BUILD_DIR=""
CMAKE_ARGS=()

while [[ $# -gt 0 ]]; do
	case "$1" in
		--zephyr)
			ZEPHYR_REPO="$2"
			shift 2
			;;
		--app)
			APP_PATH="$2"
			shift 2
			;;
		--board)
			BOARD="$2"
			shift 2
			;;
		--build-dir)
			BUILD_DIR="$2"
			shift 2
			;;
		--cmake-arg)
			CMAKE_ARGS+=("$2")
			shift 2
			;;
		-h|--help)
			usage
			exit 0
			;;
		*)
			echo "unknown argument: $1"
			usage
			exit 2
			;;
	esac
done

if [[ -z "${ZEPHYR_REPO}" || -z "${APP_PATH}" || -z "${BOARD}" || -z "${BUILD_DIR}" ]]; then
	usage
	exit 2
fi

HOST_ZEPHYR="${CODEX_WORKSPACE_ROOT}/${ZEPHYR_REPO}"
if [[ ! -d "${HOST_ZEPHYR}" ]]; then
	echo "missing Zephyr repo: ${HOST_ZEPHYR}"
	exit 1
fi

CONTAINER_ZEPHYR="${CODEX_ZEPHYR_XEN_CONTAINER_WORKSPACE}/${ZEPHYR_REPO}"

docker run --rm \
	-v "${CODEX_WORKSPACE_ROOT}:${CODEX_ZEPHYR_XEN_CONTAINER_WORKSPACE}" \
	-w "${CONTAINER_ZEPHYR}" \
	"${CODEX_ZEPHYR_XEN_IMAGE}" \
bash -lc '
set -euo pipefail
source ./zephyr-env.sh
mkdir -p "$1/Kconfig"
python3 scripts/zephyr_module.py \
  --zephyr-base="$PWD" \
  --kconfig-out "$1/Kconfig/Kconfig.modules" \
  --cmake-out "$1/zephyr_modules.txt" \
  --sysbuild-kconfig-out "$1/Kconfig/Kconfig.sysbuild.modules" \
  --sysbuild-cmake-out "$1/sysbuild_modules.txt" \
  --settings-out "$1/zephyr_settings.txt"
cmake -GNinja \
  -B "$1" \
  -S "$2" \
  -DBOARD="$3" \
  -DZEPHYR_BASE="$PWD" \
  -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
  "${@:4}"
cmake --build "$1"
' bash "${BUILD_DIR}" "${APP_PATH}" "${BOARD}" "${CMAKE_ARGS[@]}"
