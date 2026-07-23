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
    text for the related arrow label; the generated modal must render a small
    visible note marker near that arrow and reveal the full in-diagram callout
    only when hovering the marker or the arrow/label. Hovering either side must
    highlight both together. Note callouts must not make text bold on hover,
    must not trigger click or drag behavior when clicked, and must keep the
    original sequence-diagram arrow visually above any note or target overlay.
    When a note target is also listed in `diagram_focus`, prefer highlighting
    the target text and arrow without a rectangular focus box around the arrow
    label. Automatically placed notes must stay near their target arrow instead
    of drifting across the whole diagram; use explicit `x` and `y` only when
    automatic placement is not good enough.
    A diagram may also provide `code_links`, a list of objects with `target`,
    `file`, `line`, optional `title`, and optional `range`. The `target` should
    match visible SVG text, usually a sequence arrow label. `line` must point
    at the exact call or assignment that represents the arrow, while `range`
    should provide the surrounding function or block context. The generated
    modal must make that label and nearby arrow connector clickable. Clicking
    either one opens a scrollable code popover centered over the diagram with a
    translucent backdrop. The popover must show the available rendered diff
    context for the referenced file, lightly highlight the context range,
    strongly highlight the exact target line, and be closeable without leaving
    or shifting the diagram. Clicking the backdrop outside the popover must
    close it. Clickable arrow connectors should include an invisible
    rectangular hit area around the visible arrow connector and label. Hovering
    any part of a code link, including the hit area, must highlight the visible
    arrow connector and label in blue so the reader can see which code block
    will open. If the same arrow has a diagram note, hovering the hit area must
    reveal that note too.
    If the same label text appears more than once in one diagram, hover and
    active highlighting must be scoped to the specific SVG occurrence being
    hovered or clicked instead of highlighting every matching label.
    When a code link is also included in the `diagram_focus` for the currently
    opened comment, focused-comment styling must take precedence so all arrows
    relevant to that comment read as one blue group.
    Diagrams opened from
    focused comment links must still provide a toolbar control to switch back
    to the general diagram view while preserving diagram-level code-link
    navigation.
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
13. Non-trivial reports should provide a top-level `story` array in the
    canonical comments JSON. Treat `story` as the reader's guided route through
    the report, not as another comment list. Each step should explain why the
    next target matters and point at a concrete reading target: a file, a
    rendered new-file diff line, or an inline comment.
    The generated HTML must provide `Prev` and `Next` story controls, keep the
    active step visible, and scroll to code/comment targets. Supporting
    diagrams and logs should remain attached to the relevant comments rather
    than being opened from the story controls.
14. Reviewer summaries may interleave explanatory prose with proof artifacts.
    Use top-level `summary_blocks` when the summary needs to cite diagrams,
    logs, or other embedded evidence instead of only plain text. Keep the old
    top-level `summary` for backward-compatible short prose, but prefer
    `summary_blocks` for evidence-led summaries:

    ```json
    {
      "summary_blocks": [
        {"type": "text", "body": "What changed and why the evidence below matters."},
        {"type": "diagram", "diagram": "after-flow", "diagram_focus": ["registered selector"]},
        {"type": "text", "body": "What the runtime proof demonstrates."},
        {"type": "log", "log": "runtime", "log_focus": ["PASS"]}
      ]
    }
    ```

    Summary artifact previews should behave like the same artifacts attached to
    file-level or inline comments: clicking a diagram opens the diagram modal,
    clicking a log opens the log modal, and any focus fields apply only to that
    preview. Use this format for validation evidence such as build logs,
    runtime logs, trace captures, and diagrams that explain why the observed
    result proves the reviewed change works.
