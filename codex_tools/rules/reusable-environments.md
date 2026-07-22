# Reusable environment workflow

These rules apply when a task depends on a non-trivial local environment such
as a cross toolchain, SDK, emulator, hypervisor, CI runner, or generated build
context.

1. If the same environment issue blocks more than one task, stop treating it
   as a task-local inconvenience. Fix the environment problem directly before
   continuing with more task work.
2. Fix recurring environment problems in a reusable form that is fully
   portable without an AI agent. A human should be able to clone or copy the
   workspace, run the documented script, and either verify that the environment
   exists or build it from the checked-in files.
3. The Dockerfile is the source of truth for Docker-based environments. Do not
   depend on an image that only exists in one local Docker daemon unless the
   checked-in environment can rebuild an equivalent image from its Dockerfile.
   Pin versions and install every required tool explicitly enough that the
   image can be recreated later.
4. Store reusable workspace environments under `codex_tools/environments/`.
   Each environment should have its own directory with at least:

   ```text
   Dockerfile
   README.md
   scripts/
   ```

5. Every reusable environment must provide script entry points with stable
   names where they apply:

   ```text
   scripts/check.sh      # verify image/tools/cache/mount prerequisites
   scripts/build.sh      # build or update the Docker image/environment
   scripts/run.sh        # open a shell or run a command inside the environment
   scripts/validate.sh   # run the normal validation path, when one exists
   ```

   `check.sh` must be safe to run repeatedly. If the environment is missing, it
   should say what is missing and how `build.sh` will create it. `build.sh`
   must not rely on shell history or AI-provided steps.
6. Docker-based environments must be built with working DNS inside Docker
   build containers. The checked-in `build.sh` must perform a small DNS
   preflight from Docker before starting a long build, and the actual
   `docker build` invocation must use an explicit network selection such as
   `--network "${CODEX_DOCKER_BUILD_NETWORK}"`. Default the network to a
   mode with known working DNS for the environment, commonly `host` on local
   Linux workstations, and document how to override it.

   If package mirrors, source archives, or language package indexes fail
   because DNS resolution does not work, stop and fix Docker DNS for the
   environment instead of working around the failure with ad hoc host downloads
   or partially built images.
7. Keep task-specific build outputs, logs, temporary worktrees, and runtime
   artifacts inside the task directory. The reusable environment under
   `codex_tools/environments/` should contain only the machinery needed to
   recreate the environment.
8. When an environment is meant to support C or C++ work, include enough setup
   to generate a usable `compile_commands.json` for `cpp_code_map`. For Zephyr
   work this includes the Zephyr SDK, `west`, generated headers, and any QEMU,
   Xen, or board-specific tooling needed by the validation workflow.
9. Document the exact commands for checking, building, entering, and validating
   the environment. The README should also describe expected mount points and
   repository layout, for example which task directory is mounted as work
   input, where Zephyr repositories live, where generated build directories are
   written, and where logs are stored.
10. Agent-only notes are allowed in the README, but only as secondary guidance:
   they may explain recommended mount folders, repository placement, or common
   task layouts. They are not a substitute for runnable scripts.
