#!/usr/bin/env bash

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CODEX_ENV_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
export CODEX_WORKSPACE_ROOT="$(cd "${CODEX_ENV_DIR}/../../.." && pwd)"
export CODEX_MOULIN_ACT_IMAGE="${CODEX_MOULIN_ACT_IMAGE:-${ACT_IMAGE:-moulin-act:22.04}}"
export CODEX_DOCKER_BUILD_NETWORK="${CODEX_DOCKER_BUILD_NETWORK:-host}"
export CODEX_DEFAULT_MOULIN_REPO="${CODEX_DEFAULT_MOULIN_REPO:-${CODEX_WORKSPACE_ROOT}/moulin-svlad-90}"
