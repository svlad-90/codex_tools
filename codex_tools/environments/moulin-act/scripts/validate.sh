#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

usage() {
	cat <<EOF
Usage: $(basename "$0") [repo-root] [--rebuild-image] [--] [act arguments...]

Build or reuse the local act runner image and run Moulin's GitHub Actions
pull_request build job.

Environment:
  ACT_BIN                 Path to act binary. Defaults to act from PATH, then /tmp/act-bin/act.
  CODEX_MOULIN_ACT_IMAGE  Docker image tag. Defaults to moulin-act:22.04.
  CODEX_DOCKER_BUILD_NETWORK
                          Docker build network. Defaults to host.

Examples:
  codex_tools/environments/moulin-act/scripts/validate.sh /path/to/moulin
  codex_tools/environments/moulin-act/scripts/validate.sh /path/to/moulin --rebuild-image
  ACT_BIN=/tmp/act-bin/act codex_tools/environments/moulin-act/scripts/validate.sh /path/to/moulin
EOF
}

repo_root="${1:-${CODEX_DEFAULT_MOULIN_REPO}}"
if [ "$#" -gt 0 ]; then
	case "$1" in
		--rebuild-image|-h|--help|--)
			repo_root="${CODEX_DEFAULT_MOULIN_REPO}"
			;;
		*)
			shift
			;;
	esac
fi

rebuild_image=0
while [ "$#" -gt 0 ]; do
	case "$1" in
		--rebuild-image)
			rebuild_image=1
			shift
			;;
		-h|--help)
			usage
			exit 0
			;;
		--)
			shift
			break
			;;
		*)
			break
			;;
	esac
done

if [ ! -d "${repo_root}" ]; then
	echo "Moulin checkout does not exist: ${repo_root}" >&2
	exit 1
fi
repo_root="$(cd "${repo_root}" && pwd)"

act_bin="${ACT_BIN:-}"
if [ -z "${act_bin}" ]; then
	if command -v act >/dev/null 2>&1; then
		act_bin=act
	elif [ -x /tmp/act-bin/act ]; then
		act_bin=/tmp/act-bin/act
	else
		echo "error: act is not installed; set ACT_BIN or put act in PATH" >&2
		exit 1
	fi
fi

if [ "${rebuild_image}" -eq 1 ] || ! docker image inspect "${CODEX_MOULIN_ACT_IMAGE}" >/dev/null 2>&1; then
	"${SCRIPT_DIR}/build.sh"
fi

cd "${repo_root}"
exec "${act_bin}" pull_request -j build --pull=false \
	-P "ubuntu-22.04=${CODEX_MOULIN_ACT_IMAGE}" "$@"
