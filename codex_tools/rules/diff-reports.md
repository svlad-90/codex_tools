# Diff report workflow

These rules apply to diff/review reports generated under task `report/diff/`
directories.

1. Use stable commit indexes instead of commit hashes in human-facing report
   names, report titles, reviewer summaries, and explanatory comments.

   ```text
   Good: 01-dom0less-xenstore-page.html
   Good: Commit 01 initializes the dom0less XenStore page.
   Bad:  aebce38-dom0less-xenstore-page.html
   Bad:  Commit aebce38 initializes the dom0less XenStore page.
   ```

2. Number commits by their order in the reviewed series, starting from `01`.
   Keep the same index in the `.html`, `.json`, and `.patch` files for that
   commit.
3. Commit hashes may still appear inside raw git-generated patch metadata.
   Do not copy those hashes into report prose unless the user explicitly asks
   for hash-level traceability.
4. When a report is generated for a commit or another diff source that has a
   commit message, include that commit message in the HTML report. Keep it in
   its own section so the reviewer can read the author's intended rationale
   next to the annotated diff.
5. When a series is reordered or rewritten, regenerate the affected reports
   and replace stale index/hash-based alternatives instead of keeping both.
6. Keep one canonical comments JSON per HTML report. The comments JSON must use
   the same basename as the HTML report, for example `01-change.html` and
   `01-change.json`. For iterated reports, run `diff_report` with
   `--refresh-targets` so the tool refreshes target anchors in that JSON before
   rendering. The generated HTML must be self-contained for reading and must
   not depend on browser-side loading of the JSON.
7. Inline comments in the canonical JSON must keep the generated `target`
   object that records the rendered diff line number, old/new line numbers,
   line kind, line content, original diff line, whether the target was found,
   and the refresh status. `found` and `moved` comments can be treated as
   handled by the tool; `moved` means the tool updated the comment line after
   finding the old target content exactly once in the same file. `ambiguous`
   and `not_found` comments require manual attention.
8. When updating a report after the source patch changed, use
   `python -m codex_tools.diff_report` first to refresh or re-anchor existing
   comments with the information already stored in the canonical JSON. Only
   after the tool reports `not_found`, `ambiguous`, or newly relevant
   locations should the agent manually inspect the diff and apply reasoning.
   Do not manually rewrite all line numbers before attempting the tool-assisted
   update path. Use the JSON line ranges printed by the tool to inspect only
   the comments that still require attention.
9. Reports may embed explanatory SVG diagrams in comments. Declare reusable
   diagrams in the top-level `diagrams` object of the canonical comments JSON
   and reference them from file-level or inline comments with a `diagram` id.
   Prefer `svg` paths relative to the comments JSON for task-owned PlantUML
   output, and keep the `.puml` source plus the rendered adjacent `.svg` under
   `report/puml/`.
10. When a report uses diagrams, regenerate the HTML with
    `python -m codex_tools.diff_report` so the SVG is embedded into the
    self-contained report. The generated report is expected to show a compact
    SVG preview in the comment and open a modal viewer on click. The modal must
    support zoom buttons, a live zoom percentage, `Ctrl` + mouse wheel zoom
    over the diagram, mouse drag-to-pan, scrolling when zoomed, local
    `Ctrl` + `F` search over visible SVG text, closing by the backdrop, closing
    by the toolbar close button, and closing by `Esc`.
    A specific comment link may also provide `diagram_focus`, a string or list
    of strings matched against visible SVG text. Focus highlighting must apply
    only when the diagram is opened from that link, not when the same reusable
    diagram is opened from another comment or from the report-level diagrams
    section.
    A specific comment link may also provide `diagram_notes`, a list of
    objects with `target` and `text`. The `target` should match visible SVG
    text for the related arrow label; the generated modal must render the note
    as an in-diagram callout to the right of that arrow, and hovering either
    the arrow/label or the callout must highlight both together. Note callouts
    must not make text bold on hover, must not trigger click or drag behavior
    when clicked, and must keep the original sequence-diagram arrow visually
    above any note or target overlay. When a note target is also listed in
    `diagram_focus`, prefer highlighting the target text and arrow without a
    rectangular focus box around the arrow label.
11. Reports may embed validation logs in the same way as diagrams. Declare
    reusable logs in the top-level `logs` object of the canonical comments JSON
    and reference them from file-level or inline comments with a `log` id. Use
    `path` for task-owned text files relative to the comments JSON, or
    `text_inline` only for short inline snippets. Keep runtime logs under the
    task's `report/` tree, usually `report/runtime/`.
12. When a report uses logs, regenerate the HTML with
    `python -m codex_tools.diff_report` so the log text is embedded into the
    self-contained report. The generated report is expected to show a compact
    log preview in the comment and open a modal viewer on click. The modal must
    provide local search for the opened log, focus that search with
    `Ctrl` + `F`, and allow stepping through matches with the search controls
    or `Enter` / `Shift` + `Enter`.
    A specific comment link may also provide `log_focus`, a string or list of
    strings matched against full log lines. Focus highlighting must apply only
    when the log is opened from that link, not when the same reusable log is
    opened from another comment or from the report-level logs section.
