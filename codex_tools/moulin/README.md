# Moulin local validation notes

The reusable environment lives in `codex_tools/environments/moulin-act`.
Use the compatibility wrapper `run-act-build.sh` instead of manually typing
the full `act` command. The script builds or reuses the local
`moulin-act:22.04` image and runs the real GitHub Actions `build` job.

Example:

```sh
./codex_tools/moulin/run-act-build.sh ./path/to/moulin-worktree
```

Use `--rebuild-image` after changing the environment `Dockerfile`.
