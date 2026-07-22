# Moulin act environment

This reusable environment runs Moulin's real GitHub Actions `build` job
locally through `act`.

The Dockerfile builds the local runner image used for `ubuntu-22.04`. The
scripts keep the command stable and avoid depending on an image that exists
only in one Docker daemon.

## Layout

```text
codex_tools/environments/moulin-act/
  Dockerfile
  README.md
  scripts/
    check.sh
    build.sh
    run.sh
    validate.sh
```

Expected repository layout:

```text
/home/vladyslav_goncharuk/Projects/new_dev/
  moulin-svlad-90/        # default Moulin checkout used by validate.sh
  codex_tools/
```

Pass a different Moulin checkout path as the first argument to `validate.sh`.

## Commands

Check prerequisites and the local image:

```sh
codex_tools/environments/moulin-act/scripts/check.sh
```

Build or update the runner image:

```sh
codex_tools/environments/moulin-act/scripts/build.sh
```

`build.sh` first runs a small Docker DNS preflight, then builds the image with
`--network "${CODEX_DOCKER_BUILD_NETWORK}"`. The default network is `host`,
which normally gives Docker build containers working DNS on local Linux
workstations. Override it when needed:

```sh
CODEX_DOCKER_BUILD_NETWORK=bridge codex_tools/environments/moulin-act/scripts/build.sh
```

Run an interactive shell in the runner image:

```sh
codex_tools/environments/moulin-act/scripts/run.sh
```

Run the real Moulin workflow build job:

```sh
codex_tools/environments/moulin-act/scripts/validate.sh \
  /home/vladyslav_goncharuk/Projects/new_dev/moulin-svlad-90
```

Additional arguments after `--` are forwarded to `act`:

```sh
codex_tools/environments/moulin-act/scripts/validate.sh ./moulin -- --verbose
```

Useful environment variables:

- `ACT_BIN`: path to the `act` binary. Defaults to `act` from `PATH`, then
  `/tmp/act-bin/act`.
- `CODEX_MOULIN_ACT_IMAGE`: Docker image tag. Defaults to
  `moulin-act:22.04`.
- `CODEX_DOCKER_BUILD_NETWORK`: network mode for Docker DNS preflight and
  build. Defaults to `host`.
