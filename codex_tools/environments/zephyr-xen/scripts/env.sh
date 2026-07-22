#!/usr/bin/env bash
set -euo pipefail

CODEX_ENV_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CODEX_WORKSPACE_ROOT="$(cd "${CODEX_ENV_DIR}/../../.." && pwd)"

CODEX_ZEPHYR_XEN_IMAGE="${CODEX_ZEPHYR_XEN_IMAGE:-codex-zephyr-xen:zephyr4.4.1-sdk1.0.0}"
CODEX_ZEPHYR_XEN_CONTAINER_WORKSPACE="${CODEX_ZEPHYR_XEN_CONTAINER_WORKSPACE:-/workspace}"
CODEX_DOCKER_BUILD_NETWORK="${CODEX_DOCKER_BUILD_NETWORK:-host}"
