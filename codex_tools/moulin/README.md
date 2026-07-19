# Moulin local validation notes

For local Moulin CI validation, use `run-act-build.sh` instead of manually
typing the full `act` command. The script builds or reuses the local
`moulin-act:22.04` image and runs the real GitHub Actions `build` job.

Example:

```sh
/home/vladyslav_goncharuk/Projects/new_dev/codex_tools/moulin/run-act-build.sh \
  /home/vladyslav_goncharuk/Projects/new_dev/moulin-svlad-90
```

Use `--rebuild-image` after changing `act/Dockerfile`.
