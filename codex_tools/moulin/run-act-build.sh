#!/usr/bin/env bash
set -euo pipefail

repo_root=${1:-}
if [ -z "$repo_root" ]; then
    repo_root=$(pwd)
fi
repo_root=$(cd "$repo_root" && pwd)

image_name=${ACT_IMAGE:-moulin-act:22.04}
act_bin=${ACT_BIN:-}
rebuild_image=0
shift_args=0

usage() {
    cat <<EOF
Usage: $(basename "$0") [repo-root] [--rebuild-image] [--] [act arguments...]

Build the local act image if needed and run Moulin's GitHub Actions build job.

Environment:
  ACT_BIN    Path to act binary. Defaults to act from PATH, then /tmp/act-bin/act.
  ACT_IMAGE  Docker image tag to use. Defaults to moulin-act:22.04.

Examples:
  codex_tools/moulin/run-act-build.sh /path/to/moulin
  codex_tools/moulin/run-act-build.sh /path/to/moulin --rebuild-image
  ACT_BIN=/tmp/act-bin/act codex_tools/moulin/run-act-build.sh /path/to/moulin
EOF
}

if [ "$#" -gt 0 ] && [ "$1" != "--rebuild-image" ] && [ "$1" != "-h" ] && [ "$1" != "--help" ] && [ "$1" != "--" ]; then
    shift_args=1
fi
if [ "$shift_args" -eq 1 ]; then
    shift
fi

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

if [ -z "$act_bin" ]; then
    if command -v act >/dev/null 2>&1; then
        act_bin=act
    elif [ -x /tmp/act-bin/act ]; then
        act_bin=/tmp/act-bin/act
    else
        echo "error: act is not installed; set ACT_BIN or put act in PATH" >&2
        exit 1
    fi
fi

tool_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
if [ "$rebuild_image" -eq 1 ] || ! docker image inspect "$image_name" >/dev/null 2>&1; then
    docker build --network=host -t "$image_name" "$tool_dir/act"
fi

cd "$repo_root"
exec "$act_bin" pull_request -j build --pull=false -P "ubuntu-22.04=$image_name" "$@"
