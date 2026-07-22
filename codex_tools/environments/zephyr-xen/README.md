# Zephyr/Xen Environment

This reusable environment builds Zephyr/Xen tasks and produces
`compile_commands.json` files that can be used by `codex_tools.cpp_code_map`.
It is designed to be operated by a human without relying on an AI agent.

## Quick Start

From the workspace root:

```sh
codex_tools/environments/zephyr-xen/scripts/check.sh
codex_tools/environments/zephyr-xen/scripts/build.sh
codex_tools/environments/zephyr-xen/scripts/validate.sh \
  --zephyr zephyr-hypercalls/dev/zephyr-xen-hypercalls \
  --app samples/drivers/watchdog \
  --board xenvm \
  --build-dir build-pr136-wdt-cppmap
```

Use `scripts/run.sh` to enter the environment:

```sh
codex_tools/environments/zephyr-xen/scripts/run.sh
```

Or run one command inside it:

```sh
codex_tools/environments/zephyr-xen/scripts/run.sh -- \
  bash -lc 'west --version && qemu-system-aarch64 --version'
```

## Layout

The host workspace is mounted at `/workspace` in the container. Paths passed to
the scripts are workspace-relative host paths, for example:

```text
zephyr-hypercalls/dev/zephyr-xen-hypercalls
```

Task-specific build directories and logs stay in the task repository or task
directory. The environment directory contains only the Dockerfile and helper
scripts needed to recreate the tools.

## Scripts

- `scripts/check.sh` verifies Docker, the image, and key tools if the image is
  already present.
- `scripts/build.sh` builds the Docker image from this Dockerfile.
- `scripts/run.sh` opens a shell or runs a command with the workspace mounted.
- `scripts/validate.sh` configures and builds a Zephyr application with
  `CMAKE_EXPORT_COMPILE_COMMANDS=ON`.

## Image

Default image name:

```text
codex-zephyr-xen:zephyr4.4.1-sdk1.0.0
```

Override it with:

```sh
CODEX_ZEPHYR_XEN_IMAGE=my-image:tag scripts/build.sh
```

Docker builds use host networking by default so package downloads use the same
DNS resolver as the host:

```sh
CODEX_DOCKER_BUILD_NETWORK=host scripts/build.sh
```

Use another Docker network only if it has working DNS for Ubuntu mirrors,
GitHub releases, and Python package indexes.

## Zephyr Build Context

`validate.sh` is the normal way to generate a compile database:

```sh
codex_tools/environments/zephyr-xen/scripts/validate.sh \
  --zephyr zephyr-hypercalls/dev/zephyr-xen-hypercalls \
  --app samples/drivers/watchdog \
  --board xenvm \
  --build-dir build-pr136-wdt-cppmap
```

The resulting compile database is written to:

```text
zephyr-hypercalls/dev/zephyr-xen-hypercalls/build-pr136-wdt-cppmap/compile_commands.json
```

For `cpp_code_map`, run the tool inside this same image so the `/workspace/...`
paths and the Zephyr SDK sysroot from `compile_commands.json` both exist:

```sh
docker run --rm \
  -v "$PWD:/workspace" \
  -w /workspace \
  -e CODEX_CPP_CODE_MAP_RAW_WORKSPACE=/workspace/zephyr-hypercalls/dev \
  codex-zephyr-xen:zephyr4.4.1-sdk1.0.0 \
  python3 -m codex_tools.cpp_code_map parse-check \
    /workspace/zephyr-hypercalls/dev/zephyr-xen-hypercalls/drivers/watchdog/wdt_xen.c \
    --compile-db /workspace/zephyr-hypercalls/dev/zephyr-xen-hypercalls/build-pr136-wdt-cppmap
```

Adjust `CODEX_CPP_CODE_MAP_RAW_WORKSPACE` to the mounted directory that contains
the Zephyr checkout. For the workspace task layout this is usually
`/workspace/<task>/dev`.

## Xen/QEMU Runtime Inputs

The image includes QEMU for AArch64. Xen hypervisor binaries, dom0 images, domU
configuration files, and runtime logs are task-specific artifacts and should be
kept under the task directory, then mounted through the workspace mount.

Recommended task layout:

```text
<task>/dev/      repositories and runtime inputs
<task>/scripts/  task-specific QEMU/Xen launch scripts
<task>/report/   logs and validation results
```

Do not store runtime logs or generated VM images in this reusable environment
directory.
