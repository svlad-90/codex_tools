# diff_report

Generate a GitHub-style HTML diff report with optional file-level and inline
review comments.

## Usage

```sh
python -m codex_tools.diff_report \
  --repo path/to/repo \
  --range HEAD^..HEAD \
  --comments comments.json \
  --output review.html
```

You can also render an already prepared unified git diff:

```sh
python -m codex_tools.diff_report \
  --diff-file change.patch \
  --comments comments.json \
  --output review.html
```

For reports where comment anchors should be refreshed while regenerating the
HTML, enable target refresh:

```sh
python -m codex_tools.diff_report \
  --diff-file change.patch \
  --comments comments.json \
  --output review.html \
  --refresh-targets
```

In this mode the tool validates the comments JSON, updates a JSON file with
the same basename as the report, and records generated `target` anchors in
that JSON. The generated HTML is still self-contained: comments are rendered
statically into the page, and the browser does not load JSON at runtime.

Use the same-basename JSON as the editable source for the next regeneration.
For example, `review.html` should be paired with `review.json`.

Target refresh records a status for each inline comment:

- `found`: the existing `file` and `line` still point at a rendered diff line.
- `moved`: the old line no longer matched, but the old `target.content` was
  found exactly once in the same file; the tool updates `line` automatically.
- `ambiguous`: the old content exists more than once, so a human must choose.
- `not_found`: the old content was not found in the refreshed diff.

Comments with `found` and `moved` are sorted first in the JSON. Comments with
`ambiguous` or `not_found` are sorted after them, and the CLI prints their
JSON line ranges so they can be inspected without rereading the whole file.

## Comments JSON

```json
{
  "summary": "Optional plain-text summary shown above the diff.",
  "summary_blocks": [
    {
      "type": "text",
      "body": "Optional evidence-led summary paragraph."
    },
    {
      "type": "diagram",
      "diagram": "optional-diagram-id",
      "diagram_focus": ["SVG text to highlight from this summary preview"]
    },
    {
      "type": "text",
      "body": "Optional paragraph explaining the runtime proof."
    },
    {
      "type": "log",
      "log": "optional-log-id",
      "log_focus": ["Log line text to highlight from this summary preview"]
    }
  ],
  "files": {
    "path/to/file.py": "File-level review note shown under the file header."
  },
  "inline": [
    {
      "file": "path/to/file.py",
      "line": 42,
      "range": {
        "start": 42,
        "end": 45
      },
      "title": "Review comment",
      "body": "Inline review note shown under the target new-file line.",
      "diagram": "optional-diagram-id",
      "diagram_focus": ["SVG text to highlight only from this link"],
      "diagram_notes": [
        {
          "target": "SVG arrow label text",
          "text": "Callout text shown inside the opened diagram"
        }
      ],
      "log": "optional-log-id",
      "log_focus": ["Log line text to highlight only from this link"],
      "target": {
        "file": "path/to/file.py",
        "line": 42,
        "old_line": 40,
        "new_line": 42,
        "kind": "context",
        "content": "    existing_code();",
        "diff_line": "     existing_code();",
        "found": true,
        "status": "found"
      }
    }
  ],
  "diagrams": {
    "optional-diagram-id": {
      "title": "Diagram title",
      "svg": "../puml/diagram.svg",
      "code_links": [
        {
          "target": "SVG arrow label text",
          "file": "path/to/file.py",
          "line": 42,
          "title": "Open implementation",
          "range": {"start": 42, "end": 45}
        }
      ]
    }
  },
  "logs": {
    "optional-log-id": {
      "title": "Runtime log",
      "path": "../runtime/test.log"
    }
  },
  "story": [
    {
      "title": "Start with the changed entry point",
      "body": "This step explains why the first review comment matters.",
      "comment": {
        "file": "path/to/file.py",
        "line": 42
      }
    },
    {
      "title": "Then inspect the flow diagram",
      "body": "The same diagram opens with only the relevant arrow highlighted.",
      "diagram": "optional-diagram-id",
      "diagram_focus": ["SVG arrow label text"]
    },
    {
      "title": "Finish with the validation signal",
      "body": "The log opens around the line that proves the behavior.",
      "log": "optional-log-id",
      "log_focus": ["expected log line"]
    }
  ]
}
```

Inline comments are attached to new-file line numbers in the rendered diff.
Use `range` when the comment is about several rendered new-file lines instead
of one line. The range is inclusive, uses new-file line numbers, and can be
written either as `{"start": 42, "end": 45}` or `[42, 45]`. The `line` value
remains the anchor where the comment block is rendered and must be inside the
range.

The `target` object is generated by the tool in target-refresh mode. It records
the exact rendered diff line under the comment, so a later tool can re-anchor
the comment when only line numbers move.

## Reviewer Summary

Use top-level `summary` for a short plain-text reviewer summary. Use
`summary_blocks` when the summary should read like a proof narrative with
artifact previews between paragraphs. This is useful for review reports that
need to explain why the change works, not only what changed.

Supported summary block forms are:

- A plain string, rendered as a text paragraph.
- `{"type": "text", "body": "..."}` or `{"type": "paragraph", "body": "..."}`
  for an explicit text paragraph.
- `{"type": "diagram", "diagram": "diagram-id"}` to embed a diagram preview.
- `{"type": "log", "log": "log-id"}` to embed a log preview.

Summary diagram and log previews use the same modal viewers as comment
artifacts. `diagram_focus`, `diagram_notes`, and `log_focus` are scoped to that
specific preview, so the same reusable artifact can be opened with different
highlighting from the summary, file comments, inline comments, or story.

## Story

Use the top-level `story` array when the report should guide the reader through
the review in a deliberate order. The generated report shows a sticky story
panel with `Prev` and `Next` controls. Selecting a story step scrolls to the
targeted file, diff line, or review comment. Supporting diagrams and logs stay
attached to the comments that explain them, so the story panel remains a compact
navigation route instead of becoming a second artifact index.

Each story step requires `title` and one target. Use `body` for the narrative
sentence that explains why the reader is looking at this step. Supported
targets are:

- `{"file": "path/to/file.py"}` to scroll to a changed file.
- `{"file": "path/to/file.py", "line": 42}` to scroll to a rendered new-file
  diff line.
- `{"comment": {"file": "path/to/file.py", "line": 42}}` to scroll to an
  inline review comment.
When the reader opens a diagram or log from the selected comment, the modal can
show the active story step title and body above the artifact.

## Diagrams

Comments may reference SVG diagrams through a `diagram` id. Diagrams are
declared once in the top-level `diagrams` object and can use either `svg`, a
path to a local `.svg` file relative to the comments JSON, or `svg_inline`, an
inline SVG string. The generated HTML embeds the SVG content directly, shows a
preview in the comment, and opens a modal when the preview is clicked. The
modal supports zoom buttons, a live zoom percentage, `Ctrl` + mouse wheel zoom
over the diagram, drag-to-pan with the mouse, scrolling at larger scales,
local `Ctrl` + `F` search over visible SVG text, close by backdrop click, close
by the toolbar button, and close by `Esc`.

Use `diagram_focus` on a specific file-level or inline comment link when the
same reusable diagram should open with context-specific SVG text highlighted.
The focus terms are matched against visible SVG text and are applied only when
the diagram is opened from that particular comment link.

Use `diagram_notes` on a specific file-level or inline comment link when the
opened diagram needs explanatory callouts inside the SVG. Each note uses
`target` to match visible SVG text, typically an arrow label, and `text` for
the callout body. The diagram shows a small note marker next to the matched
arrow, and hovering either the marker or the arrow/label opens the full
callout. Note callouts do not react to clicks, do not make text bold on hover,
and keep the original sequence arrow above the callout overlays. If a note
target is also included in `diagram_focus`, the tool highlights the target
label and sequence arrow without drawing a focus box around that arrow label.
Automatically placed callouts stay near their target arrow instead of drifting
across the whole diagram; set explicit `x` and `y` only when the automatic
placement is not good enough.

Use `code_links` on a diagram when an important SVG arrow should open the
corresponding rendered diff code. Each link uses `target` to match visible SVG
text, usually the arrow label, plus `file` and `line` to point at a rendered
new-file line in the diff. Use `line` for the exact call or assignment that
represents the diagram arrow, and use optional `range` for the surrounding
function or block context. In the opened diagram, the matched label and
nearby arrow connector become clickable. Clicking either one opens a
scrollable code popover over the diagram. The popover shows the available
rendered diff context for that file, lightly highlights the context range,
strongly highlights the exact target line, and
can be closed without leaving or shifting the diagram. The popover is modal
inside the diagram viewer: it appears centered over a translucent backdrop,
keeps the diagram at the same scroll position, closes when the backdrop is
clicked, and renders highlighted rows as continuous full-width code lines.
Clickable arrow connectors also get an invisible rectangular hit area around
the visible arrow connector and label. Hovering any part of a code link,
including the hit area, highlights the visible arrow connector and label in
blue so the reader can see what will open before clicking. If the same arrow
has a diagram note, that note also opens on hit-area hover. When the same
label text appears more than once in a
diagram, hover and active highlighting are scoped to the specific SVG
occurrence that the reader is pointing at.
When a code link is also part of the `diagram_focus` for the currently opened
comment, the focused-comment styling wins so all arrows relevant to that
comment read as one blue group.

## Logs

Comments may reference logs through a `log` id. Logs are declared once in the
top-level `logs` object and can use either `path`, a local text file path
relative to the comments JSON, or `text_inline`, an inline log string. The
generated HTML embeds the log text directly, shows a compact preview in the
comment, and opens the clicked log in a modal. The modal search field filters
within the opened log only; `Ctrl` + `F` focuses that local search field, and
`Enter` / `Shift` + `Enter` moves through matches.

Use `log_focus` on a specific file-level or inline comment link when the same
reusable log should open with context-specific lines highlighted. The focus
terms are matched against full log lines and are applied only when the log is
opened from that particular comment link.
