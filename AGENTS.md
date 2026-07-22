# Workspace instructions

Before working in this directory or any of its subdirectories, read and follow
all instruction files in `codex_tools/rules/`.

These rules apply to the entire workspace unless a more specific `AGENTS.md`
deeper in the directory tree overrides them.

Current rule files:

- `codex_tools/rules/python-code.md`
- `codex_tools/rules/cpp-code.md`
- `codex_tools/rules/reusable-environments.md`
- `codex_tools/rules/findings.md`
- `codex_tools/rules/git-commits.md`
- `codex_tools/rules/diff-reports.md`

Workspace-local skills live under `codex_tools/skills/`. When a task matches a
workspace-local skill, read that skill's `SKILL.md` before acting and follow it
in addition to the rule files above.

## Task layout

Every task in this workspace must live in its own top-level directory under the
workspace root. Each task directory must use this layout:

- `TASK_CONTEXT.md` - active task context, decisions, branches, repositories,
  validation status, discovered constraints, and remaining work.
- `dev/` - repositories, reproducers, workspaces, build files, and other
  development inputs for the task.
- `Dockerfile/` - task-specific Dockerfiles, container build context files,
  environment scripts, and notes needed to reproduce the task environment.
- `scripts/` - task-specific scripts for repeated routine work.
- `report/` - review reports, notes, logs, generated HTML/JSON reports, and
  other non-source task artifacts.
- `report/diff/` - diff, patch, patch-bundle artifacts, generated HTML diff
  review reports, and the comments JSON used to generate those reports.
- `report/puml/` - PlantUML diagrams and generated diagram assets. Every
  `.puml` diagram added or changed for a task must be rendered to an adjacent
  `.svg` file before the task is considered complete.

Diff/review reports must be delivered as GitHub-style HTML generated with
`python -m codex_tools.diff_report`. Place the generated HTML, the comments
JSON used by the tool, and the source diff/patch under `report/diff/`.
Markdown files may be used for short notes or navigation, but they are not a
substitute for the HTML diff review report.

Comments in diff reports, diagrams, and explanatory notes must be written for a
reader with strong application, middleware, and architecture experience but
limited systems-programming background. For low-level topics such as memory
copying, bit operations, assembly, Xen, Zephyr, U-Boot, boot flows, MMIO,
interrupts, PFNs/GFNs, page tables, cache flushes, and hypercalls, do not rely
on terse systems shorthand. Introduce each new term in plain language, state
what problem the step solves, explain what would break if the step were absent,
and only then name the exact variable, register, constant, or API. When several
low-level terms are involved, repeat the role of each term locally instead of
assuming the reader remembers it from earlier comments.

When updating an existing diff/review report for the same task or review scope,
replace the old artifacts instead of keeping stale alternatives. Remove any
superseded HTML, JSON, diff, or patch files for the old version once the new
report has been generated and verified.

Before working inside a task directory, read that task's `TASK_CONTEXT.md` and
keep it updated as the task progresses.

Move repeated routine work into `scripts/` when doing so is useful. The decision
to create or use a script is left to the model's judgment; prefer scripts when
they reduce outgoing tokens, avoid repeated reasoning, or make recurring work
easier to rerun reliably. Do not create scripts for one-off commands or tiny
tasks when a script would add more overhead than value.

Follow `codex_tools/rules/git-commits.md` for commit message formatting.

Workspace infrastructure such as `.git`, `.agents`, `.codex`, and
`codex_tools/` stays at the workspace root and is not a task.
