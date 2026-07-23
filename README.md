# Codex workspace tools

This repository contains a portable Codex workspace setup: the root
`AGENTS.md` instructions plus the `codex_tools/` helper package used by those
instructions.

The goal is to make the working style reproducible. Clone this repository as a
workspace root, put task directories next to `codex_tools/`, and Codex will have
the same rules, helper commands, review-report tooling, and validation
conventions available in every task.

## What belongs in this repository

This repository tracks reusable workspace infrastructure only:

- `AGENTS.md` - workspace-level instructions that apply to the root and all
  task directories.
- `codex_tools/` - local helper modules, rule files, and workflow utilities.
- `.gitignore` - keeps task directories, build outputs, caches, and local
  artifacts out of this setup repository.

Task-specific work does not belong in this repository. Task directories are
created at the workspace root and are intentionally ignored by Git so the same
workspace can contain many unrelated development efforts without mixing them
into the setup history.

## Workspace contract

Every task lives in its own top-level directory under the workspace root. A task
directory is expected to contain:

- `TASK_CONTEXT.md` for active context, decisions, branch information,
  validation status, constraints, and remaining work.
- `dev/` for repositories, reproducers, workspaces, build files, and other
  development inputs.
- `Dockerfile/` for task-specific Dockerfiles, container build contexts,
  environment scripts, and reproduction notes.
- `scripts/` for task-specific scripts that make repeated routine work cheaper
  and more reliable.
- `report/` for notes, logs, generated reports, and other non-source artifacts.
- `report/diff/` for source diffs, patch bundles, HTML diff review reports, and
  the JSON comments used to generate those reports.
- `report/puml/` for PlantUML diagrams and adjacent rendered SVG outputs.

The `scripts/` directory is a workspace directive, not a mandatory abstraction
for every command. Use scripts when they reduce repeated reasoning, reduce
outgoing tokens, or make recurring validation and reproduction steps easier to
rerun. Avoid scripts for one-off commands or tiny tasks where a script would add
more overhead than value.

## Codex rules

The root `AGENTS.md` requires Codex to read and follow all rule files in
`codex_tools/rules/` before working in the workspace.

Current rule files:

- `python-code.md` - use `python -m codex_tools.code_map` when inspecting,
  editing, or validating Python code.
- `cpp-code.md` - use `python -m codex_tools.cpp_code_map` when inspecting,
  editing, or validating C and C++ code.
- `reusable-environments.md` - keep reusable container environments under
  `codex_tools/environments/` and task-specific runtime material under the
  task directory.
- `findings.md` - write review findings with clear severity, references, and
  actionable explanation.
- `diff-reports.md` - keep diff review artifacts consistent, self-contained,
  and evidence-led when validation artifacts matter.
- `git-commits.md` - keep commit messages wrapped and include the required
  `Signed-off-by` trailer.

More specific `AGENTS.md` files inside task directories may override the root
instructions for their subtree.

## Included tools

### `codex_tools.code_map`

Python source inspection and guarded editing support. It can map file structure,
resolve symbols, inspect exact spans, and parse-check changed Python files.

Typical commands:

```sh
python -m codex_tools.code_map map path/to/file.py
python -m codex_tools.code_map symbol-get path/to/file.py --symbol Name
python -m codex_tools.code_map parse-check path/to/file.py
```

### `codex_tools.cpp_code_map`

C and C++ source inspection and validation support built around libclang and
compile databases. It helps map C++ files, inspect symbols, and parse-check
changes with explicit build context.

Typical commands:

```sh
python -m codex_tools.cpp_code_map map path/to/file.cpp --compile-db build
python -m codex_tools.cpp_code_map symbol-get path/to/file.cpp \
  --symbol Namespace::Name --compile-db build
python -m codex_tools.cpp_code_map parse-check path/to/file.cpp \
  --compile-db build
```

### `codex_tools.diff_report`

GitHub-style HTML diff review report generation. Review artifacts should live
under a task's `report/diff/` directory, including the source diff, comments
JSON, and generated HTML.

Reports can include file-level comments, inline comments, guided story steps,
diagram and log previews, diagram-to-code links, and evidence-led
`Reviewer Summary` sections that interleave prose with diagram or log previews.

Typical command:

```sh
python -m codex_tools.diff_report \
  --diff-file report/diff/changes.diff \
  --comments report/diff/comments.json \
  --output report/diff/review.html
```

### `codex_tools.yaml_map`

YAML structure inspection helpers for workflows and configuration files.

### `codex_tools.moulin`

Moulin-specific local validation helpers, including an `act` Dockerfile and
runner script for reproducing GitHub Actions workflows locally.

## Deployment model

Use this repository as the root of a Codex workspace:

```sh
git clone git@github.com:svlad-90/codex_tools.git codex-workspace
cd codex-workspace
```

Then create task directories next to `codex_tools/`:

```text
codex-workspace/
  AGENTS.md
  codex_tools/
  some-task/
    TASK_CONTEXT.md
    dev/
    Dockerfile/
    scripts/
    report/
```

Because `.gitignore` ignores everything by default and explicitly re-includes
only the reusable setup files, task directories remain local unless they are
managed by their own nested repositories.

## Maintenance notes

- Keep workspace-wide behavior in the root `AGENTS.md`.
- Keep reusable Codex helper behavior in `codex_tools/`.
- Keep language-specific and workflow-specific requirements in
  `codex_tools/rules/`.
- Keep generated caches, task outputs, downloaded repositories, and local
  reproduction artifacts out of this repository.
- Commit messages must follow `codex_tools/rules/git-commits.md`.
