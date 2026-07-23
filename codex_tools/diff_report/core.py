from __future__ import annotations

import html
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class InlineComment:
    file_path: str
    line: int
    body: str
    title: str = "Review comment"
    line_range: tuple[int, int] | None = None
    diagram: str | None = None
    log: str | None = None
    diagram_focus: tuple[str, ...] = ()
    log_focus: tuple[str, ...] = ()
    diagram_notes: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class Diagram:
    diagram_id: str
    title: str
    svg: str
    code_links: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class LogAttachment:
    log_id: str
    title: str
    text: str


@dataclass(frozen=True)
class ReviewComments:
    file_comments: dict[str, str]
    inline_comments: dict[tuple[str, int], tuple[InlineComment, ...]]
    diagrams: dict[str, Diagram]
    logs: dict[str, LogAttachment]
    file_diagrams: dict[str, str]
    file_logs: dict[str, str]
    file_diagram_focus: dict[str, tuple[str, ...]]
    file_log_focus: dict[str, tuple[str, ...]]
    file_diagram_notes: dict[str, tuple[dict[str, Any], ...]]
    summary: str | None = None


@dataclass(frozen=True)
class DiffSource:
    diff_text: str
    stat_text: str
    label: str
    commit: str | None = None
    subject: str | None = None
    message: str | None = None


class DiffReportError(ValueError):
    pass


_TARGET_STATUS_ORDER = {
    "found": 0,
    "moved": 1,
    "ambiguous": 2,
    "not_found": 3,
}


def compact_help() -> str:
    return "\n".join(
        [
            "diff_report --repo <git_repo> --range HEAD^..HEAD --output report.html [--comments comments.json]",
            "diff_report --diff-file diff.patch --output report.html [--comments comments.json]",
            "diff_report --diff-file diff.patch --output report.html --comments comments.json --refresh-targets",
            "",
            "comments.json schema:",
            "{",
            '  "summary": "optional markdown-free text",',
            '  "files": {"path/to/file.py": "file-level comment"},',
            '  "inline": [',
            '    {"file": "path/to/file.py", "line": 42, "range": {"start": 42, "end": 45}, "body": "comment", "title": "optional", "diagram": "optional-id", "diagram_focus": ["important SVG text"], "diagram_notes": [{"text": "note", "target": "SVG text"}], "log": "optional-log-id", "log_focus": ["important log line text"]}',
            "  ],",
            '  "diagrams": {"optional-id": {"title": "Diagram title", "svg": "report/puml/diagram.svg", "code_links": [{"target": "SVG arrow label", "file": "path/to/file.py", "line": 42, "title": "Code target"}]}},',
            '  "logs": {"optional-log-id": {"title": "Runtime log", "path": "report/runtime/test.log"}}',
            "}",
        ]
    )


def generate_report(
    *,
    output_path: Path,
    title: str,
    repo_path: Path | None = None,
    rev_range: str = "HEAD^..HEAD",
    diff_file: Path | None = None,
    comments_file: Path | None = None,
    context: int = 80,
    display_label: str | None = None,
    refresh_targets: bool = False,
) -> None:
    source = _load_diff_source(repo_path, rev_range, diff_file, context, display_label)
    comments = _load_comments(comments_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered_comments = comments
    if refresh_targets:
        comments_output_path = output_path.with_suffix(".json")
        comments_payload = _load_comments_payload(comments_file)
        comments_payload = _enrich_comments_payload(source.diff_text, comments_payload)
        comments_json = json.dumps(comments_payload, indent=2, ensure_ascii=False) + "\n"
        comments_output_path.write_text(comments_json, encoding="utf-8")
        _print_refresh_attention(comments_output_path, comments_payload, comments_json)
        rendered_comments = _comments_from_payload(
            comments_payload,
            base_dir=comments_output_path.parent,
        )
    output_path.write_text(
        render_html_report(title, source, rendered_comments),
        encoding="utf-8",
    )


def render_html_report(
    title: str,
    source: DiffSource,
    comments: ReviewComments,
) -> str:
    files = _diff_files(source.diff_text)
    comment_count = _comment_count(comments)
    comments_status = f'<strong id="comment-count">{comment_count}</strong> review comments loaded.'
    parts: list[str] = []
    parts.append(_html_header(title))
    parts.append(
        f"""
<main>
  <header>
    <h1>{_esc(title)}</h1>
    <p>GitHub-style unified diff report with optional inline review comments.</p>
    <p id="comments-status">{comments_status}</p>
    <div class="meta">
      <div><span class="label">Diff source</span><code>{_esc(source.label)}</code></div>
      <div><span class="label">Subject</span>{_esc(source.subject or "n/a")}</div>
    </div>
  </header>
"""
    )
    if comments.summary:
        parts.append(
            f'  <section><h2>Reviewer Summary</h2>'
            f'<p class="review-summary">{_esc(comments.summary)}</p></section>\n'
        )
    if source.message:
        parts.append(
            f'  <section><h2>Commit Message</h2>'
            f'<pre class="commit-message">{_esc(source.message)}</pre></section>\n'
        )
    if comments.diagrams:
        parts.append(_render_diagrams_section(comments))
    if comments.logs:
        parts.append(_render_logs_section(comments))
    if comment_count:
        parts.append(_render_comments_index(comments))
    parts.append('  <section><h2>Changed Files</h2><div class="toc">\n')
    for file_path in files:
        parts.append(f'    <a href="#{_anchor(file_path)}">{_esc(file_path)}</a>\n')
    parts.append(f'  </div><pre class="stat">{_esc(source.stat_text)}</pre></section>\n')
    parts.append(_render_diff(source.diff_text, comments))
    if comments.diagrams or comments.logs:
        parts.append(_render_diagram_modal(comments))
    parts.append("</main>\n</body>\n</html>\n")
    return "".join(parts)


def _comment_count(comments: ReviewComments) -> int:
    return len(comments.file_comments) + sum(len(items) for items in comments.inline_comments.values())


def _render_comments_index(comments: ReviewComments) -> str:
    parts = ['  <section><h2>Review Comments</h2>\n']
    if comments.file_comments:
        parts.append("    <h3>File-level comments</h3>\n    <ul class=\"comment-index\">\n")
        for file_path, body in sorted(comments.file_comments.items()):
            parts.append(
                f'      <li><a href="#{_anchor(file_path)}">{_esc(file_path)}</a>: '
                f'{_esc(body)}</li>\n'
            )
        parts.append("    </ul>\n")

    inline_items = [
        comment
        for key in sorted(comments.inline_comments)
        for comment in comments.inline_comments[key]
    ]
    if inline_items:
        parts.append("    <h3>Inline comments</h3>\n    <ol class=\"comment-index\">\n")
        for comment in inline_items:
            location = _comment_location(comment)
            parts.append(
                f'      <li><a href="#{_comment_anchor(comment.file_path, comment.line)}">'
                f'{_esc(location)}</a> '
                f'<strong>{_esc(comment.title)}</strong>: {_esc(comment.body)}</li>\n'
            )
        parts.append("    </ol>\n")
    parts.append("  </section>\n")
    return "".join(parts)


def _render_diagrams_section(comments: ReviewComments) -> str:
    parts = ['  <section><h2>Diagrams</h2><div class="diagram-list">\n']
    for diagram in sorted(comments.diagrams.values(), key=lambda item: item.diagram_id):
        parts.append(_render_diagram_preview(diagram))
    parts.append("  </div></section>\n")
    return "".join(parts)


def _render_logs_section(comments: ReviewComments) -> str:
    parts = ['  <section><h2>Logs</h2><div class="diagram-list">\n']
    for log in sorted(comments.logs.values(), key=lambda item: item.log_id):
        parts.append(_render_log_preview(log))
    parts.append("  </div></section>\n")
    return "".join(parts)


def _load_diff_source(
    repo_path: Path | None,
    rev_range: str,
    diff_file: Path | None,
    context: int,
    display_label: str | None,
) -> DiffSource:
    if diff_file is not None:
        diff_text = diff_file.read_text(encoding="utf-8")
        subject, message = _commit_message_from_patch(diff_text)
        return DiffSource(
            diff_text=diff_text,
            stat_text="Loaded from diff file; git stat is unavailable.",
            label=display_label or str(diff_file),
            subject=subject,
            message=message,
        )
    if repo_path is None:
        raise DiffReportError("--repo is required unless --diff-file is used")
    if not repo_path.exists():
        raise DiffReportError(f"Repository path does not exist: {repo_path}")
    base, head = _parse_rev_range(rev_range)
    diff_text = _git(repo_path, ["diff", "--find-renames", f"--unified={context}", base, head])
    stat_text = _git(repo_path, ["diff", "--stat", base, head])
    commit = _git(repo_path, ["rev-parse", head]).strip()
    subject = _git(repo_path, ["log", "-1", "--pretty=%s", head]).strip()
    message = _git(repo_path, ["log", "-1", "--format=%B", head]).strip()
    return DiffSource(
        diff_text=diff_text,
        stat_text=stat_text,
        label=display_label or f"{repo_path} {base}..{head}",
        commit=None if display_label else commit,
        subject=subject,
        message=message or None,
    )


def _load_comments(comments_file: Path | None) -> ReviewComments:
    payload = _load_comments_payload(comments_file)
    base_dir = comments_file.parent if comments_file is not None else None
    return _comments_from_payload(payload, base_dir=base_dir)


def _comments_from_payload(
    payload: dict[str, Any],
    *,
    base_dir: Path | None = None,
) -> ReviewComments:
    if not isinstance(payload, dict):
        raise DiffReportError("Comments JSON must be an object")

    raw_files = payload.get("files", {})
    if not isinstance(raw_files, dict):
        raise DiffReportError("comments.files must be an object")
    file_comments: dict[str, str] = {}
    file_diagrams: dict[str, str] = {}
    file_logs: dict[str, str] = {}
    file_diagram_focus: dict[str, tuple[str, ...]] = {}
    file_log_focus: dict[str, tuple[str, ...]] = {}
    file_diagram_notes: dict[str, tuple[dict[str, Any], ...]] = {}
    for path, value in raw_files.items():
        path_key = str(path)
        if isinstance(value, dict):
            file_comments[path_key] = str(value.get("body", ""))
            if "diagram" in value:
                file_diagrams[path_key] = str(value["diagram"])
            if "diagram_focus" in value:
                file_diagram_focus[path_key] = _focus_terms(value["diagram_focus"], field="diagram_focus")
            if "diagram_notes" in value:
                file_diagram_notes[path_key] = _diagram_notes(value["diagram_notes"])
            if "log" in value:
                file_logs[path_key] = str(value["log"])
            if "log_focus" in value:
                file_log_focus[path_key] = _focus_terms(value["log_focus"], field="log_focus")
        else:
            file_comments[path_key] = str(value)

    diagrams = _diagrams_from_payload(payload, base_dir=base_dir)
    logs = _logs_from_payload(payload, base_dir=base_dir)

    grouped: dict[tuple[str, int], list[InlineComment]] = {}
    raw_inline = payload.get("inline", [])
    if not isinstance(raw_inline, list):
        raise DiffReportError("comments.inline must be a list")
    for item in raw_inline:
        if not isinstance(item, dict):
            raise DiffReportError("comments.inline entries must be objects")
        file_path = str(_required(item, "file"))
        line = int(_required(item, "line"))
        line_range = _comment_line_range(item.get("range"), line=line)
        body = str(_required(item, "body"))
        title = str(item.get("title", "Review comment"))
        diagram = str(item["diagram"]) if "diagram" in item else None
        if diagram is not None and diagram not in diagrams:
            raise DiffReportError(f"unknown diagram referenced by inline comment: {diagram}")
        log = str(item["log"]) if "log" in item else None
        if log is not None and log not in logs:
            raise DiffReportError(f"unknown log referenced by inline comment: {log}")
        diagram_focus = _focus_terms(item.get("diagram_focus", ()), field="diagram_focus")
        log_focus = _focus_terms(item.get("log_focus", ()), field="log_focus")
        diagram_notes = _diagram_notes(item.get("diagram_notes", ()))
        grouped.setdefault((file_path, line), []).append(
            InlineComment(
                file_path=file_path,
                line=line,
                line_range=line_range,
                body=body,
                title=title,
                diagram=diagram,
                log=log,
                diagram_focus=diagram_focus,
                log_focus=log_focus,
                diagram_notes=diagram_notes,
            )
        )
    for file_path, diagram in file_diagrams.items():
        if diagram not in diagrams:
            raise DiffReportError(f"unknown diagram referenced by file comment {file_path}: {diagram}")
    for file_path, log in file_logs.items():
        if log not in logs:
            raise DiffReportError(f"unknown log referenced by file comment {file_path}: {log}")
    return ReviewComments(
        file_comments=file_comments,
        inline_comments={key: tuple(value) for key, value in grouped.items()},
        diagrams=diagrams,
        logs=logs,
        file_diagrams=file_diagrams,
        file_logs=file_logs,
        file_diagram_focus=file_diagram_focus,
        file_log_focus=file_log_focus,
        file_diagram_notes=file_diagram_notes,
        summary=str(payload["summary"]) if "summary" in payload else None,
    )


def _diagrams_from_payload(
    payload: dict[str, Any],
    *,
    base_dir: Path | None,
) -> dict[str, Diagram]:
    raw_diagrams = payload.get("diagrams", {})
    if raw_diagrams in ({}, None):
        return {}
    if not isinstance(raw_diagrams, dict):
        raise DiffReportError("comments.diagrams must be an object")

    diagrams: dict[str, Diagram] = {}
    for diagram_id, raw in raw_diagrams.items():
        diagram_key = str(diagram_id)
        if not isinstance(raw, dict):
            raise DiffReportError(f"diagram entry must be an object: {diagram_key}")
        title = str(raw.get("title", diagram_key))
        if "svg_inline" in raw:
            svg = _normalize_svg(str(raw["svg_inline"]), source=f"diagram {diagram_key}")
        elif "svg" in raw:
            svg_path = Path(str(raw["svg"]))
            if not svg_path.is_absolute() and base_dir is not None:
                svg_path = base_dir / svg_path
            svg = _read_svg_file(svg_path)
        else:
            raise DiffReportError(f"diagram entry is missing svg or svg_inline: {diagram_key}")
        code_links = _diagram_code_links(raw, diagram_key)
        diagrams[diagram_key] = Diagram(
            diagram_id=diagram_key,
            title=title,
            svg=svg,
            code_links=code_links,
        )
    return diagrams


def _diagram_code_links(raw: dict[str, Any], diagram_key: str) -> tuple[dict[str, Any], ...]:
    raw_links = raw.get("code_links", ())
    if raw_links in ((), [], None):
        return ()
    if not isinstance(raw_links, list):
        raise DiffReportError(f"diagram code_links must be a list: {diagram_key}")

    links: list[dict[str, Any]] = []
    for index, raw_link in enumerate(raw_links):
        if not isinstance(raw_link, dict):
            raise DiffReportError(f"diagram code_links[{index}] must be an object: {diagram_key}")
        target = str(raw_link.get("target", "")).strip()
        file_path = str(raw_link.get("file", "")).strip()
        line = raw_link.get("line")
        if not target:
            raise DiffReportError(f"diagram code_links[{index}] is missing target: {diagram_key}")
        if not file_path:
            raise DiffReportError(f"diagram code_links[{index}] is missing file: {diagram_key}")
        if not isinstance(line, int):
            raise DiffReportError(f"diagram code_links[{index}] line must be an integer: {diagram_key}")
        link: dict[str, Any] = {
            "target": target,
            "file": file_path,
            "line": line,
            "title": str(raw_link.get("title", target)),
        }
        if "range" in raw_link:
            link["range"] = raw_link["range"]
        links.append(link)
    return tuple(links)


def _read_svg_file(svg_path: Path) -> str:
    if svg_path.suffix.lower() != ".svg":
        raise DiffReportError(f"diagram file must be an .svg file: {svg_path}")
    if not svg_path.exists():
        raise DiffReportError(f"diagram SVG file does not exist: {svg_path}")
    svg = svg_path.read_text(encoding="utf-8")
    return _normalize_svg(svg, source=str(svg_path))


def _logs_from_payload(
    payload: dict[str, Any],
    *,
    base_dir: Path | None,
) -> dict[str, LogAttachment]:
    raw_logs = payload.get("logs", {})
    if raw_logs in ({}, None):
        return {}
    if not isinstance(raw_logs, dict):
        raise DiffReportError("comments.logs must be an object")

    logs: dict[str, LogAttachment] = {}
    for log_id, raw in raw_logs.items():
        log_key = str(log_id)
        if not isinstance(raw, dict):
            raise DiffReportError(f"log entry must be an object: {log_key}")
        title = str(raw.get("title", log_key))
        if "text_inline" in raw:
            text = str(raw["text_inline"])
        elif "path" in raw:
            log_path = Path(str(raw["path"]))
            if not log_path.is_absolute() and base_dir is not None:
                log_path = base_dir / log_path
            text = _read_log_file(log_path)
        else:
            raise DiffReportError(f"log entry is missing path or text_inline: {log_key}")
        logs[log_key] = LogAttachment(log_id=log_key, title=title, text=text)
    return logs


def _read_log_file(log_path: Path) -> str:
    if not log_path.exists():
        raise DiffReportError(f"log file does not exist: {log_path}")
    if not log_path.is_file():
        raise DiffReportError(f"log path is not a file: {log_path}")
    return log_path.read_text(encoding="utf-8", errors="replace")


def _normalize_svg(svg: str, *, source: str) -> str:
    if "<svg" not in svg:
        raise DiffReportError(f"diagram does not look like SVG: {source}")
    if re.search(r"<\s*script\b", svg, flags=re.IGNORECASE):
        raise DiffReportError(f"diagram SVG must not contain script tags: {source}")
    svg = re.sub(r"^\s*<\?xml[^>]*>\s*", "", svg)
    svg = re.sub(r"^\s*<!DOCTYPE[^>]*>\s*", "", svg, flags=re.IGNORECASE)
    return svg


def _load_comments_payload(comments_file: Path | None) -> dict[str, Any]:
    if comments_file is None:
        return {}
    payload = json.loads(comments_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DiffReportError("Comments JSON must be an object")
    return payload


def _enrich_comments_payload(diff_text: str, payload: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(payload)
    raw_inline = enriched.get("inline", [])
    if not isinstance(raw_inline, list):
        raise DiffReportError("comments.inline must be a list")

    targets = _diff_line_targets(diff_text)
    content_targets = _diff_content_targets(targets)
    enriched_inline: list[Any] = []
    for item in raw_inline:
        if not isinstance(item, dict):
            raise DiffReportError("comments.inline entries must be objects")
        file_path = str(_required(item, "file"))
        line = int(_required(item, "line"))
        enriched_item = dict(item)
        line_range = _comment_line_range(enriched_item.get("range"), line=line)
        if line_range is not None:
            enriched_item["range"] = {"start": line_range[0], "end": line_range[1]}
        target = targets.get((file_path, line))
        if target is not None:
            enriched_item["target"] = _target_with_status(target, "found")
            enriched_inline.append(enriched_item)
            continue

        old_target = item.get("target", {})
        old_content = old_target.get("content") if isinstance(old_target, dict) else None
        if isinstance(old_content, str) and old_content:
            matches = content_targets.get((file_path, old_content), [])
            if len(matches) == 1:
                moved_target = _target_with_status(
                    matches[0],
                    "moved",
                    previous_line=line,
                )
                enriched_item["line"] = moved_target["line"]
                if line_range is not None:
                    line_delta = int(moved_target["line"]) - line
                    enriched_item["range"] = {
                        "start": line_range[0] + line_delta,
                        "end": line_range[1] + line_delta,
                    }
                enriched_item["target"] = moved_target
                enriched_inline.append(enriched_item)
                continue
            if len(matches) > 1:
                enriched_item["target"] = {
                    "file": file_path,
                    "line": line,
                    "found": False,
                    "status": "ambiguous",
                    "candidate_lines": [match["line"] for match in matches],
                    "content": old_content,
                }
                enriched_inline.append(enriched_item)
                continue

        enriched_item["target"] = {
            "file": file_path,
            "line": line,
            "found": False,
            "status": "not_found",
            "content": old_content,
        }
        enriched_inline.append(enriched_item)
    enriched["inline"] = sorted(enriched_inline, key=_inline_sort_key)
    return enriched


def _diff_content_targets(
    targets: dict[tuple[str, int], dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    content_targets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for target in targets.values():
        content = target.get("content")
        file_path = target.get("file")
        if isinstance(file_path, str) and isinstance(content, str) and content:
            content_targets.setdefault((file_path, content), []).append(target)
    return content_targets


def _target_with_status(
    target: dict[str, Any],
    status: str,
    *,
    previous_line: int | None = None,
) -> dict[str, Any]:
    updated = dict(target)
    updated["found"] = True
    updated["status"] = status
    if previous_line is not None and previous_line != updated.get("line"):
        updated["previous_line"] = previous_line
    return updated


def _inline_sort_key(item: Any) -> tuple[int, str, int, str]:
    if not isinstance(item, dict):
        return (99, "", 0, "")
    target = item.get("target", {})
    status = target.get("status") if isinstance(target, dict) else None
    return (
        _TARGET_STATUS_ORDER.get(str(status), 99),
        str(item.get("file", "")),
        int(item.get("line", 0)),
        str(item.get("title", "")),
    )


def _print_refresh_attention(
    comments_path: Path,
    payload: dict[str, Any],
    comments_json: str,
) -> None:
    raw_inline = payload.get("inline", [])
    if not isinstance(raw_inline, list):
        return

    ranges = _inline_item_line_ranges(comments_json)
    attention: list[tuple[int, int, dict[str, Any]]] = []
    moved = 0
    for index, item in enumerate(raw_inline):
        if not isinstance(item, dict):
            continue
        target = item.get("target", {})
        status = target.get("status") if isinstance(target, dict) else None
        if status == "moved":
            moved += 1
        if status in {"ambiguous", "not_found"}:
            start, end = ranges[index] if index < len(ranges) else (0, 0)
            attention.append((start, end, item))

    if moved:
        print(f"refresh-targets: {comments_path}: moved={moved} auto-updated")
    if not attention:
        print(f"refresh-targets: {comments_path}: attention=0")
        return

    print(f"refresh-targets: {comments_path}: attention={len(attention)}")
    for start, end, item in attention:
        target = item.get("target", {})
        status = target.get("status") if isinstance(target, dict) else "unknown"
        location = f"{item.get('file')}:{item.get('line')}"
        title = str(item.get("title", "Review comment"))
        line_range = f"{start}-{end}" if start and end else "unknown"
        print(f"  lines {line_range}: {status} {location} {title}")


def _inline_item_line_ranges(comments_json: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    in_inline = False
    object_start: int | None = None
    object_depth = 0

    for line_no, line in enumerate(comments_json.splitlines(), start=1):
        stripped = line.strip()
        if not in_inline:
            if stripped == '"inline": [':
                in_inline = True
            continue
        if object_start is None and (stripped == "]" or stripped == "],"):
            break
        if object_start is None and stripped.startswith("{"):
            object_start = line_no
            object_depth = 0
        if object_start is not None:
            object_depth += line.count("{")
            object_depth -= line.count("}")
            if object_depth == 0:
                ranges.append((object_start, line_no))
                object_start = None

    return ranges


def _comment_line_range(value: Any, *, line: int) -> tuple[int, int] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        start = int(_required(value, "start"))
        end = int(_required(value, "end"))
    elif isinstance(value, list) and len(value) == 2:
        start = int(value[0])
        end = int(value[1])
    else:
        raise DiffReportError(
            "comments.inline[].range must be an object with start/end or a [start, end] array"
        )
    if start < 1 or end < start:
        raise DiffReportError("comments.inline[].range must use positive inclusive line numbers")
    if line < start or line > end:
        raise DiffReportError("comments.inline[].line must be inside comments.inline[].range")
    return (start, end)


def _diff_line_targets(diff_text: str) -> dict[tuple[str, int], dict[str, Any]]:
    targets: dict[tuple[str, int], dict[str, Any]] = {}
    current_file: str | None = None
    old_no: int | None = None
    new_no: int | None = None

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            current_file = _file_from_diff_header(raw_line)
            old_no = None
            new_no = None
            continue

        if current_file is None:
            continue

        hunk_match = _HUNK_RE.match(raw_line)
        if hunk_match:
            old_no = int(hunk_match.group(1))
            new_no = int(hunk_match.group(3))
            continue

        if _is_diff_metadata(raw_line):
            continue

        if old_no is None or new_no is None:
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            targets[(current_file, new_no)] = {
                "file": current_file,
                "line": new_no,
                "old_line": None,
                "new_line": new_no,
                "kind": "add",
                "content": raw_line[1:],
                "diff_line": raw_line,
                "found": True,
            }
            new_no += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            old_no += 1
        else:
            targets[(current_file, new_no)] = {
                "file": current_file,
                "line": new_no,
                "old_line": old_no,
                "new_line": new_no,
                "kind": "context",
                "content": raw_line[1:] if raw_line.startswith(" ") else raw_line,
                "diff_line": raw_line,
                "found": True,
            }
            old_no += 1
            new_no += 1

    return targets


def _render_diff(diff_text: str, comments: ReviewComments) -> str:
    parts: list[str] = []
    current_file: str | None = None
    old_no: int | None = None
    new_no: int | None = None
    table_open = False
    comment_ranges = _comment_line_ranges(comments)
    inline_comments_by_render_line = _inline_comments_by_render_line(comments)

    def close_file() -> None:
        nonlocal table_open, current_file
        if table_open:
            parts.append("      </tbody>\n    </table>\n")
            table_open = False
        if current_file is not None:
            parts.append("  </article>\n")

    for raw_line in diff_text.splitlines():
        if raw_line.startswith("diff --git "):
            close_file()
            current_file = _file_from_diff_header(raw_line)
            old_no = None
            new_no = None
            parts.append(
                f'  <article class="file" id="{_anchor(current_file)}" '
                f'data-file="{_esc(current_file)}">\n'
            )
            parts.append(f'    <div class="file-header">{_esc(current_file)}</div>\n')
            if current_file in comments.file_comments:
                parts.append(
                    f'    <div class="file-comment"><strong>File review note:</strong> '
                    f'{_esc(comments.file_comments[current_file])}'
                    f'{_render_comment_assets(comments, comments.file_diagrams.get(current_file), comments.file_logs.get(current_file), comments.file_diagram_focus.get(current_file, ()), comments.file_log_focus.get(current_file, ()), comments.file_diagram_notes.get(current_file, ()))}'
                    "</div>\n"
                )
            parts.append('    <table class="diff"><tbody>\n')
            table_open = True
            parts.append(_diff_row("header", "", "", raw_line))
            continue

        if current_file is None:
            continue

        hunk_match = _HUNK_RE.match(raw_line)
        if hunk_match:
            old_no = int(hunk_match.group(1))
            new_no = int(hunk_match.group(3))
            parts.append(_diff_row("hunk", "...", "...", raw_line))
            continue

        if _is_diff_metadata(raw_line):
            parts.append(_diff_row("header", "", "", raw_line))
            continue

        if old_no is None or new_no is None:
            parts.append(_diff_row("header", "", "", raw_line))
            continue

        if raw_line.startswith("+") and not raw_line.startswith("+++"):
            line_no = new_no
            parts.append(
                _diff_row(
                    "add",
                    "",
                    str(new_no),
                    raw_line,
                    current_file,
                    line_no,
                    _comment_target_classes(comment_ranges, current_file, line_no),
                )
            )
            parts.append(
                _render_inline_comments(
                    inline_comments_by_render_line,
                    comments,
                    current_file,
                    line_no,
                )
            )
            new_no += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            parts.append(_diff_row("del", str(old_no), "", raw_line))
            old_no += 1
        else:
            line_no = new_no
            parts.append(
                _diff_row(
                    "ctx",
                    str(old_no),
                    str(new_no),
                    raw_line,
                    current_file,
                    line_no,
                    _comment_target_classes(comment_ranges, current_file, line_no),
                )
            )
            parts.append(
                _render_inline_comments(
                    inline_comments_by_render_line,
                    comments,
                    current_file,
                    line_no,
                )
            )
            old_no += 1
            new_no += 1

    close_file()
    return "".join(parts)


def _comment_line_ranges(comments: ReviewComments) -> dict[str, list[tuple[int, int]]]:
    ranges: dict[str, list[tuple[int, int]]] = {}
    for (file_path, line), inline_comments in comments.inline_comments.items():
        for comment in inline_comments:
            ranges.setdefault(file_path, []).append(comment.line_range or (line, line))
    return ranges


def _inline_comments_by_render_line(
    comments: ReviewComments,
) -> dict[tuple[str, int], list[InlineComment]]:
    grouped: dict[tuple[str, int], list[InlineComment]] = {}
    for (file_path, line), inline_comments in comments.inline_comments.items():
        for comment in inline_comments:
            render_line = comment.line_range[1] if comment.line_range is not None else line
            grouped.setdefault((file_path, render_line), []).append(comment)
    return grouped


def _comment_target_classes(
    ranges: dict[str, list[tuple[int, int]]],
    file_path: str,
    line: int,
) -> tuple[str, ...]:
    for start, end in ranges.get(file_path, ()):
        if start <= line <= end:
            classes = ["comment-target"]
            if line == start:
                classes.append("comment-target-start")
            if line == end:
                classes.append("comment-target-end")
            if start == end:
                classes.append("comment-target-single")
            return tuple(classes)
    return ()


def _render_inline_comments(
    grouped_comments: dict[tuple[str, int], list[InlineComment]],
    comments: ReviewComments,
    file_path: str,
    line: int,
) -> str:
    rendered: list[str] = []
    for comment in grouped_comments.get((file_path, line), ()):
        location = _comment_location(comment)
        rendered.append(
            '      <tr class="comment-row"><td colspan="3">'
            f'<div class="review-comment" id="{_comment_anchor(file_path, comment.line)}">'
            f'<div class="title">{_esc(comment.title)} on {_esc(location)}</div>'
            f'<div class="body">{_esc(comment.body)}'
            f'{_render_comment_assets(comments, comment.diagram, comment.log, comment.diagram_focus, comment.log_focus, comment.diagram_notes)}</div>'
            "</div></td></tr>\n"
        )
    return "".join(rendered)


def _comment_location(comment: InlineComment) -> str:
    if comment.line_range is None:
        return f"{comment.file_path}:{comment.line}"
    start, end = comment.line_range
    if start == end:
        return f"{comment.file_path}:{start}"
    return f"{comment.file_path}:{start}-{end}"


def _render_comment_assets(
    comments: ReviewComments,
    diagram_id: str | None,
    log_id: str | None,
    diagram_focus: tuple[str, ...] = (),
    log_focus: tuple[str, ...] = (),
    diagram_notes: tuple[dict[str, Any], ...] = (),
) -> str:
    return (
        _render_comment_diagram(comments, diagram_id, diagram_focus, diagram_notes)
        + _render_comment_log(comments, log_id, log_focus)
    )


def _render_comment_diagram(
    comments: ReviewComments,
    diagram_id: str | None,
    focus_terms: tuple[str, ...] = (),
    notes: tuple[dict[str, Any], ...] = (),
) -> str:
    if not diagram_id:
        return ""
    diagram = comments.diagrams.get(diagram_id)
    if diagram is None:
        return ""
    return (
        '<div class="diagram-preview-wrap">'
        f'{_render_diagram_preview(diagram, focus_terms, notes)}'
        "</div>"
    )


def _render_comment_log(
    comments: ReviewComments,
    log_id: str | None,
    focus_terms: tuple[str, ...] = (),
) -> str:
    if not log_id:
        return ""
    log = comments.logs.get(log_id)
    if log is None:
        return ""
    return (
        '<div class="diagram-preview-wrap">'
        f'{_render_log_preview(log, focus_terms)}'
        "</div>"
    )


def _render_diagram_preview(
    diagram: Diagram,
    focus_terms: tuple[str, ...] = (),
    notes: tuple[dict[str, Any], ...] = (),
) -> str:
    safe_id = _anchor(diagram.diagram_id)
    focus_attr = _focus_attr("data-diagram-focus", focus_terms)
    notes_attr = _json_attr("data-diagram-notes", notes)
    return (
        '<button type="button" class="diagram-preview" '
        f'data-diagram-id="{_esc(safe_id)}"{focus_attr}{notes_attr} aria-label="Open diagram: {_esc(diagram.title)}">'
        f'<span class="diagram-preview-title">{_esc(diagram.title)}</span>'
        f'<span class="diagram-preview-canvas">{diagram.svg}</span>'
        "</button>\n"
    )


def _render_log_preview(log: LogAttachment, focus_terms: tuple[str, ...] = ()) -> str:
    safe_id = _anchor(log.log_id)
    focus_attr = _focus_attr("data-log-focus", focus_terms)
    return (
        '<button type="button" class="diagram-preview log-preview" '
        f'data-log-id="{_esc(safe_id)}"{focus_attr} aria-label="Open log: {_esc(log.title)}">'
        f'<span class="diagram-preview-title">{_esc(log.title)}</span>'
        f'<pre class="log-preview-text">{_esc(_log_excerpt(log.text))}</pre>'
        "</button>\n"
    )


def _render_diagram_modal(comments: ReviewComments) -> str:
    parts = ['<div class="diagram-modal" id="diagram-modal" hidden>\n']
    parts.append('  <div class="diagram-backdrop" data-diagram-close></div>\n')
    parts.append('  <div class="diagram-dialog" role="dialog" aria-modal="true" aria-labelledby="diagram-modal-title">\n')
    parts.append('    <div class="diagram-toolbar">\n')
    parts.append('      <h2 id="diagram-modal-title">Diagram</h2>\n')
    parts.append('      <div class="diagram-tools">\n')
    parts.append('        <input id="diagram-search" type="search" placeholder="Search" aria-label="Search opened asset">\n')
    parts.append('        <span id="diagram-search-count" class="diagram-search-count"></span>\n')
    parts.append('        <button type="button" id="diagram-general-view" data-diagram-general hidden>General view</button>\n')
    parts.append('        <button type="button" data-diagram-search="prev" aria-label="Previous search match">Prev</button>\n')
    parts.append('        <button type="button" data-diagram-search="next" aria-label="Next search match">Next</button>\n')
    parts.append('        <button type="button" data-diagram-zoom="out" data-diagram-zoom-tool aria-label="Zoom out">-</button>\n')
    parts.append(
        '        <button type="button" data-diagram-zoom="reset" data-diagram-zoom-tool aria-label="Reset zoom">'
        '<span id="diagram-zoom-label">100%</span></button>\n'
    )
    parts.append('        <button type="button" data-diagram-zoom="in" data-diagram-zoom-tool aria-label="Zoom in">+</button>\n')
    parts.append('        <button type="button" data-diagram-close aria-label="Close diagram">&times;</button>\n')
    parts.append("      </div>\n")
    parts.append("    </div>\n")
    parts.append('    <div class="diagram-scroll" id="diagram-modal-content"></div>\n')
    parts.append("  </div>\n")
    parts.append("</div>\n")
    parts.append('<div class="diagram-store" hidden>\n')
    for diagram in comments.diagrams.values():
        safe_id = _anchor(diagram.diagram_id)
        links_attr = _json_attr("data-code-links", diagram.code_links)
        parts.append(
            f'  <template id="diagram-template-{_esc(safe_id)}" '
            f'data-title="{_esc(diagram.title)}"{links_attr}>{diagram.svg}</template>\n'
        )
    for log in comments.logs.values():
        safe_id = _anchor(log.log_id)
        parts.append(
            f'  <template id="log-template-{_esc(safe_id)}" '
            f'data-title="{_esc(log.title)}">'
            f'<pre class="log-view-text">{_esc(log.text)}</pre></template>\n'
        )
    parts.append("</div>\n")
    parts.append(_diagram_script())
    return "".join(parts)


def _diff_row(
    kind: str,
    old_no: str,
    new_no: str,
    text: str,
    file_path: str | None = None,
    new_line: int | None = None,
    extra_classes: tuple[str, ...] = (),
) -> str:
    attrs = ""
    if file_path is not None and new_line is not None:
        attrs = (
            f' id="{_line_anchor(file_path, new_line)}"'
            f' data-file="{_esc(file_path)}" data-new-line="{new_line}"'
        )
    class_name = " ".join((kind, *extra_classes))
    return (
        f'      <tr class="{class_name}"{attrs}><td class="num">{_esc(old_no)}</td>'
        f'<td class="num">{_esc(new_no)}</td><td class="code">{_esc(text)}</td></tr>\n'
    )


def _html_header(title: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_esc(title)}</title>
  <style>
    :root {{
      --bg: #f6f8fa;
      --panel: #ffffff;
      --border: #d0d7de;
      --text: #24292f;
      --muted: #57606a;
      --add-bg: #e6ffec;
      --del-bg: #ffebe9;
      --hunk-bg: #ddf4ff;
      --comment-bg: #fff8c5;
      --comment-border: #d4a72c;
      --code-bg: #f6f8fa;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    main {{ width: min(1280px, calc(100% - 32px)); margin: 24px auto; }}
    header, section, .file {{ background: var(--panel); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 16px; }}
    header, section {{ padding: 20px; }}
    h1, h2 {{ margin: 0 0 12px; line-height: 1.2; }}
    h1 {{ font-size: 26px; }}
    h2 {{ font-size: 18px; }}
    p {{ margin: 0 0 10px; }}
    .review-summary {{ white-space: pre-line; }}
    .commit-message {{ margin: 0; padding: 12px; background: var(--code-bg); border-radius: 6px; white-space: pre-wrap; overflow-wrap: anywhere; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    code {{ background: rgba(175,184,193,.2); border-radius: 4px; padding: 1px 5px; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
    pre.stat {{ margin: 10px 0 0; padding: 12px; background: var(--code-bg); border-radius: 6px; overflow-x: auto; }}
    .meta {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; margin-top: 14px; }}
    .meta div {{ border: 1px solid var(--border); border-radius: 6px; padding: 10px; background: #fbfcfe; }}
    .label {{ display: block; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; margin-bottom: 3px; }}
    .toc a {{ display: inline-block; margin: 0 8px 8px 0; color: #0969da; text-decoration: none; }}
    .toc a:hover {{ text-decoration: underline; }}
    .comment-index {{ margin: 0 0 16px; padding-left: 22px; }}
    .comment-index li {{ margin: 0 0 8px; }}
    .comment-index a {{ color: #0969da; text-decoration: none; }}
    .comment-index a:hover {{ text-decoration: underline; }}
    .file-header {{ padding: 10px 12px; border-bottom: 1px solid var(--border); background: #f6f8fa; font-weight: 700; position: sticky; top: 0; z-index: 1; }}
    .file-comment {{ margin: 10px 12px; padding: 10px 12px; border-left: 4px solid var(--comment-border); background: var(--comment-bg); border-radius: 6px; }}
    table.diff {{ width: 100%; border-collapse: collapse; table-layout: fixed; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12.5px; }}
    .diff td {{ vertical-align: top; border: 0; padding: 0; }}
    .num {{ width: 56px; padding: 0 8px !important; color: var(--muted); text-align: right; user-select: none; border-right: 1px solid var(--border) !important; }}
    .code {{ white-space: pre-wrap; overflow-wrap: anywhere; padding: 0 10px !important; }}
    tr.add .num, tr.add .code {{ background: var(--add-bg); }}
    tr.del .num, tr.del .code {{ background: var(--del-bg); }}
    tr.ctx .num, tr.ctx .code {{ background: #fff; }}
    tr.hunk .num, tr.hunk .code {{ background: var(--hunk-bg); color: #0969da; }}
    tr.header .num, tr.header .code {{ background: #f6f8fa; color: var(--muted); font-weight: 700; }}
    tr.comment-target .num, tr.comment-target .code {{ background: #fffdf0; }}
    tr.comment-target.add .num, tr.comment-target.add .code {{ background: linear-gradient(to right, rgba(255,248,197,.46), rgba(255,248,197,.46)), var(--add-bg); }}
    tr.comment-target .num:first-child {{ box-shadow: inset 4px 0 0 var(--comment-border); }}
    tr.comment-target-start .num, tr.comment-target-start .code {{ box-shadow: inset 0 1px 0 rgba(212,167,44,.55); }}
    tr.comment-target-end .num, tr.comment-target-end .code {{ box-shadow: inset 0 -1px 0 rgba(212,167,44,.35); }}
    tr.comment-target-start .num:first-child {{ box-shadow: inset 4px 0 0 var(--comment-border), inset 0 1px 0 rgba(212,167,44,.55); }}
    tr.comment-target-end .num:first-child {{ box-shadow: inset 4px 0 0 var(--comment-border), inset 0 -1px 0 rgba(212,167,44,.35); }}
    tr.comment-target-single .num:first-child {{ box-shadow: inset 4px 0 0 var(--comment-border), inset 0 1px 0 rgba(212,167,44,.55), inset 0 -1px 0 rgba(212,167,44,.35); }}
    tr.comment-row td {{ background: linear-gradient(to right, rgba(255,253,240,.78) 0 112px, transparent 112px); padding: 0 !important; }}
    .review-comment {{ position: relative; margin: 6px 18px 14px 112px; border: 1px solid rgba(212,167,44,.55); border-left-width: 4px; background: var(--comment-bg); border-radius: 6px; box-shadow: 0 1px 2px rgba(31,35,40,.08); overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .review-comment::before {{ content: ""; position: absolute; top: -7px; left: -4px; width: 4px; height: 7px; background: var(--comment-border); }}
    .review-comment .title {{ padding: 8px 10px; font-weight: 700; border-bottom: 1px solid rgba(212,167,44,.35); background: rgba(255,255,255,.38); }}
    .review-comment .body {{ padding: 9px 10px; }}
    .diagram-list {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
    .diagram-preview-wrap {{ margin-top: 10px; }}
    .diagram-preview {{ display: block; width: min(420px, 100%); border: 1px solid var(--border); border-radius: 6px; background: #fff; padding: 0; text-align: left; cursor: zoom-in; overflow: hidden; color: inherit; }}
    .diagram-preview:hover {{ border-color: #0969da; box-shadow: 0 0 0 2px rgba(9,105,218,.12); }}
    .diagram-preview-title {{ display: block; padding: 7px 9px; border-bottom: 1px solid var(--border); background: #f6f8fa; font-weight: 700; }}
    .diagram-preview-canvas {{ display: flex; align-items: center; justify-content: center; height: 180px; padding: 10px; overflow: hidden; background: #fff; }}
    .diagram-preview-canvas svg {{ max-width: 100%; max-height: 100%; width: auto; height: auto; }}
    .log-preview {{ cursor: pointer; }}
    .log-preview-text {{ height: 180px; margin: 0; padding: 10px; overflow: hidden; background: #0d1117; color: #e6edf3; font: 12px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; text-align: left; }}
    .diagram-modal[hidden] {{ display: none; }}
    .diagram-modal {{ position: fixed; inset: 0; z-index: 1000; }}
    .diagram-backdrop {{ position: absolute; inset: 0; background: rgba(31,35,40,.55); }}
    .diagram-dialog {{ position: absolute; inset: 32px; display: flex; flex-direction: column; min-width: 0; min-height: 0; background: var(--panel); border: 1px solid var(--border); border-radius: 8px; box-shadow: 0 16px 48px rgba(31,35,40,.28); }}
    .diagram-toolbar {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border-bottom: 1px solid var(--border); background: #f6f8fa; }}
    .diagram-toolbar h2 {{ margin: 0; font-size: 16px; }}
    .diagram-tools {{ display: flex; align-items: center; gap: 6px; }}
    .diagram-tools input {{ width: 220px; height: 32px; border: 1px solid var(--border); border-radius: 6px; padding: 0 9px; font: inherit; }}
    .diagram-search-count {{ min-width: 54px; color: var(--muted); font-size: 12px; text-align: center; }}
    .diagram-tools button {{ min-width: 36px; height: 32px; border: 1px solid var(--border); border-radius: 6px; background: #fff; cursor: pointer; font: inherit; }}
    .diagram-tools button:hover {{ border-color: #0969da; color: #0969da; }}
    .diagram-scroll {{ position: relative; flex: 1; min-height: 0; overflow: auto; padding: 18px; background: #fff; }}
    .diagram-code-overlay {{ position: absolute; z-index: 4; display: flex; align-items: center; justify-content: center; padding: 28px; background: rgba(31,35,40,.42); box-sizing: border-box; }}
    .diagram-code-popover {{ width: min(820px, 100%); max-height: min(620px, 100%); border: 1px solid var(--border); border-radius: 8px; background: #fff; box-shadow: 0 12px 32px rgba(31,35,40,.24); overflow: hidden; }}
    .diagram-code-overlay[hidden] {{ display: none; }}
    .diagram-code-popover-header {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border-bottom: 1px solid var(--border); background: #f6f8fa; }}
    .diagram-code-popover-title {{ font-weight: 700; }}
    .diagram-code-popover-close {{ width: 30px; height: 30px; border: 1px solid var(--border); border-radius: 6px; background: #fff; cursor: pointer; font: inherit; }}
    .diagram-code-popover-close:hover {{ border-color: #0969da; color: #0969da; }}
    .diagram-code-popover-body {{ max-height: min(540px, calc(100vh - 260px)); padding: 10px 12px; overflow: auto; }}
    .diagram-code-link-item {{ display: block; margin: 0 0 10px; padding: 9px; border: 1px solid var(--border); border-radius: 6px; background: #fff; color: inherit; }}
    .diagram-code-link-title {{ display: block; font-weight: 700; margin-bottom: 4px; }}
    .diagram-code-link-location {{ display: block; color: var(--muted); font: 12px/1.35 ui-monospace, SFMono-Regular, Consolas, monospace; margin-bottom: 6px; }}
    .diagram-code-link-code {{ display: block; max-height: 390px; overflow: auto; padding: 8px; border-radius: 4px; background: var(--code-bg); font: 12px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre; }}
    .diagram-code-line {{ display: block; min-width: max-content; padding: 0 4px; }}
    .diagram-code-context-line {{ background: rgba(255,248,197,.36); }}
    .diagram-code-target-line {{ background: rgba(255,223,93,.82); border-left: 3px solid #9a6700; padding-left: 1px; font-weight: 700; }}
    .diagram-scroll[data-mode="diagram"] .diagram-zoom-stage {{ cursor: grab; }}
    .diagram-scroll.is-panning, .diagram-scroll.is-panning .diagram-zoom-stage {{ cursor: grabbing; user-select: none; }}
    .diagram-zoom-stage {{ transform-origin: 0 0; width: max-content; min-width: 100%; }}
    .diagram-zoom-stage svg {{ display: block; max-width: none; height: auto; }}
    .log-view-text {{ margin: 0; min-width: 100%; color: #e6edf3; background: #0d1117; padding: 14px; border-radius: 6px; font: 12.5px/1.45 ui-monospace, SFMono-Regular, Consolas, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }}
    .asset-focus-line {{ display: block; margin: 0 -4px; padding: 0 4px; background: rgba(255, 171, 112, .32); border-left: 3px solid #fb8500; }}
    mark.asset-search-match {{ background: #fff8c5; color: inherit; padding: 0 1px; border-radius: 2px; }}
    mark.asset-search-current {{ background: #ffab70; outline: 1px solid #fb8500; }}
    svg .asset-focus-box {{ fill: rgba(219, 234, 254, .68); stroke: #2563eb; stroke-width: 2px; rx: 4px; ry: 4px; }}
    svg .asset-focus-connector {{ stroke: #1d4ed8 !important; stroke-width: 3px !important; opacity: .95; filter: drop-shadow(0 0 2px rgba(255,255,255,.95)); }}
    svg line.asset-focus-connector, svg path.asset-focus-connector, svg polyline.asset-focus-connector {{ stroke-dasharray: 10 7; animation: focus-dash-flow 1.1s linear infinite; }}
    svg line.asset-focus-connector-reverse, svg path.asset-focus-connector-reverse, svg polyline.asset-focus-connector-reverse {{ animation-name: focus-dash-flow-reverse; }}
    svg polygon.asset-focus-connector {{ fill: #1d4ed8 !important; opacity: .95; filter: drop-shadow(0 0 2px rgba(255,255,255,.95)); animation: focus-arrow-pulse 1.1s ease-in-out infinite; }}
    svg .asset-focus-match {{ fill: #111827; stroke: none; font-weight: 800; }}
    svg .diagram-note-panel {{ opacity: 0; pointer-events: none; transition: opacity .12s ease; }}
    svg .diagram-note-hover .diagram-note-panel, svg .diagram-note-hotspot:hover .diagram-note-panel {{ opacity: 1; pointer-events: auto; }}
    svg .diagram-note-box {{ fill: #f8fafc; stroke: #2563eb; stroke-width: 1.8px; rx: 6px; ry: 6px; filter: drop-shadow(0 2px 4px rgba(15,23,42,.22)); }}
    svg .diagram-note-text {{ fill: #111827; font: 12px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; pointer-events: none; }}
    svg .diagram-note-link {{ fill: none; stroke: #64748b; stroke-width: 1.6px; opacity: .86; filter: drop-shadow(0 0 2px rgba(255,255,255,.95)); }}
    svg .diagram-note-marker {{ fill: #eff6ff; stroke: #2563eb; stroke-width: 1.8px; filter: drop-shadow(0 1px 2px rgba(15,23,42,.2)); }}
    svg .diagram-note-marker-text {{ fill: #1d4ed8; font: 700 13px -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; text-anchor: middle; dominant-baseline: central; pointer-events: none; }}
    svg .diagram-note-hotspot {{ cursor: pointer; }}
    svg .diagram-note-hover .diagram-note-box, svg .diagram-note-hotspot:hover .diagram-note-box {{ fill: #dbeafe; stroke: #1d4ed8; stroke-width: 2.4px; }}
    svg .diagram-note-hover .diagram-note-marker, svg .diagram-note-hotspot:hover .diagram-note-marker {{ fill: #dbeafe; stroke: #1d4ed8; stroke-width: 2.4px; }}
    svg .diagram-note-hover .diagram-note-link, svg .diagram-note-hotspot:hover .diagram-note-link {{ stroke: #1d4ed8; stroke-width: 2.1px; opacity: 1; }}
    svg .diagram-note-hover .diagram-note-text, svg .diagram-note-hotspot:hover .diagram-note-text {{ fill: #1e3a8a; }}
    svg .diagram-code-link-target {{ cursor: pointer; fill: #047857 !important; text-decoration: underline; text-decoration-thickness: 1.5px; }}
    svg .diagram-code-link-connector {{ cursor: pointer; stroke: #047857 !important; stroke-width: 2.6px !important; opacity: .96; }}
    svg polygon.diagram-code-link-connector {{ fill: #047857 !important; }}
    svg .diagram-code-link-hit-area {{ cursor: pointer; fill: rgba(29,78,216,.01) !important; stroke: rgba(29,78,216,.01) !important; stroke-width: 1px !important; opacity: .01; pointer-events: all; }}
    svg .diagram-code-link-hover {{ stroke: #1d4ed8 !important; fill: #1d4ed8 !important; opacity: 1 !important; filter: drop-shadow(0 0 2px rgba(255,255,255,.95)); }}
    svg text.diagram-code-link-hover, svg tspan.diagram-code-link-hover {{ fill: #1e3a8a !important; stroke: none !important; font-weight: 800; }}
    svg .diagram-code-link-hit-area.diagram-code-link-hover {{ stroke: rgba(29,78,216,.01) !important; fill: rgba(29,78,216,.01) !important; opacity: .01 !important; filter: none; }}
    svg .diagram-code-link-active {{ filter: drop-shadow(0 0 3px rgba(4,120,87,.65)); }}
    svg .asset-focus-connector.diagram-code-link-connector {{ stroke: #1d4ed8 !important; stroke-width: 3px !important; opacity: .95; }}
    svg polygon.asset-focus-connector.diagram-code-link-connector {{ fill: #1d4ed8 !important; }}
    svg text.asset-focus-match.diagram-code-link-target, svg tspan.asset-focus-match.diagram-code-link-target {{ fill: #1e3a8a !important; stroke: none !important; font-weight: 800; }}
    svg .asset-focus-related-hover {{ stroke: #1d4ed8 !important; fill: #1d4ed8 !important; opacity: 1 !important; filter: drop-shadow(0 0 2px rgba(255,255,255,.95)); }}
    svg text.asset-focus-related-hover, svg tspan.asset-focus-related-hover {{ fill: #1e3a8a !important; stroke: none !important; }}
    svg .asset-search-match {{ fill: #cf222e; stroke: #cf222e; font-weight: 700; }}
    svg .asset-search-current {{ filter: drop-shadow(0 0 3px #fb8500); }}
    @keyframes focus-dash-flow {{ from {{ stroke-dashoffset: 0; }} to {{ stroke-dashoffset: -17; }} }}
    @keyframes focus-dash-flow-reverse {{ from {{ stroke-dashoffset: 0; }} to {{ stroke-dashoffset: 17; }} }}
    @keyframes focus-arrow-pulse {{ 0%, 100% {{ opacity: .55; }} 50% {{ opacity: .9; }} }}
    @media (prefers-reduced-motion: reduce) {{
      svg line.asset-focus-connector, svg path.asset-focus-connector, svg polyline.asset-focus-connector, svg polygon.asset-focus-connector {{ animation: none; }}
    }}
  </style>
</head>
<body>
"""


def _diagram_script() -> str:
    return """<script>
(function () {
  const modal = document.getElementById("diagram-modal");
  if (!modal) {
    return;
  }
  const title = document.getElementById("diagram-modal-title");
  const content = document.getElementById("diagram-modal-content");
  const zoomLabel = document.getElementById("diagram-zoom-label");
  const searchInput = document.getElementById("diagram-search");
  const searchCount = document.getElementById("diagram-search-count");
  const generalViewButton = document.getElementById("diagram-general-view");
  const zoomTools = Array.from(document.querySelectorAll("[data-diagram-zoom-tool]"));
  let scale = 1;
  let mode = "";
  let activeFocusTerms = [];
  let activeNotes = [];
  let activeCodeLinks = [];
  let activeCodeLinkHoverInstance = "";
  let activeCodeLinkHoverTarget = "";
  let searchMatches = [];
  let searchIndex = -1;
  let isPanning = false;
  let panStartX = 0;
  let panStartY = 0;
  let panStartLeft = 0;
  let panStartTop = 0;

  function setScale(nextScale) {
    scale = Math.max(0.25, Math.min(4, nextScale));
    if (zoomLabel) {
      zoomLabel.textContent = Math.round(scale * 100) + "%";
    }
    const stage = content.querySelector(".diagram-zoom-stage");
    if (stage) {
      stage.style.transform = "scale(" + scale + ")";
      stage.style.marginRight = ((scale - 1) * stage.scrollWidth) + "px";
      stage.style.marginBottom = ((scale - 1) * stage.scrollHeight) + "px";
    }
  }

  function setMode(nextMode) {
    mode = nextMode;
    content.dataset.mode = mode;
    for (const tool of zoomTools) {
      tool.hidden = mode !== "diagram";
    }
  }

  function clearSearch() {
    searchMatches = [];
    searchIndex = -1;
    if (searchCount) {
      searchCount.textContent = "";
    }
    if (mode === "log") {
      renderLogView("", activeFocusTerms);
      return;
    }
    for (const node of content.querySelectorAll(".asset-search-match, .asset-search-current")) {
      node.classList.remove("asset-search-match", "asset-search-current");
    }
  }

  function clearFocus() {
    activeFocusTerms = [];
    activeNotes = [];
    for (const node of content.querySelectorAll(".diagram-note-layer")) {
      node.remove();
    }
    for (const node of content.querySelectorAll(".asset-focus-box")) {
      node.remove();
    }
    for (const node of content.querySelectorAll(".asset-focus-connector")) {
      node.classList.remove("asset-focus-connector", "asset-focus-connector-reverse");
    }
    for (const node of content.querySelectorAll(".asset-focus-match")) {
      node.classList.remove("asset-focus-match", "asset-focus-related-hover");
    }
    for (const node of content.querySelectorAll(".asset-focus-related-hover")) {
      node.classList.remove("asset-focus-related-hover");
    }
    for (const node of content.querySelectorAll(".diagram-code-link-hover")) {
      node.classList.remove("diagram-code-link-hover");
    }
    activeCodeLinkHoverInstance = "";
    activeCodeLinkHoverTarget = "";
    for (const node of content.querySelectorAll(".diagram-code-link-hit-area")) {
      node.remove();
    }
    if (mode === "log") {
      renderLogView(searchInput ? searchInput.value : "", activeFocusTerms);
    }
    if (generalViewButton) {
      generalViewButton.hidden = true;
    }
  }

  function parseFocus(value) {
    if (!value) {
      return [];
    }
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) {
        return parsed.map(String).filter(Boolean);
      }
    } catch (error) {
      return [String(value)];
    }
    return [String(value)];
  }

  function matchesAnyTerm(text, terms) {
    const lowerText = text.toLowerCase();
    return terms.some(function (term) {
      return lowerText.includes(String(term).toLowerCase());
    });
  }

  function addSvgFocusBox(node) {
    const svg = node.ownerSVGElement;
    if (!svg || typeof node.getBBox !== "function") {
      return;
    }
    let box;
    try {
      box = node.getBBox();
    } catch (error) {
      return;
    }
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    const paddingX = 6;
    const paddingY = 4;
    rect.setAttribute("class", "asset-focus-box");
    rect.setAttribute("x", String(box.x - paddingX));
    rect.setAttribute("y", String(box.y - paddingY));
    rect.setAttribute("width", String(box.width + paddingX * 2));
    rect.setAttribute("height", String(box.height + paddingY * 2));
    const parent = node.parentNode || svg;
    parent.insertBefore(rect, node);
  }

  function isSvgConnector(node) {
    if (!node || !node.tagName) {
      return false;
    }
    if (node.classList && node.classList.contains("diagram-code-link-hit-area")) {
      return false;
    }
    const tag = node.tagName.toLowerCase();
    return tag === "line" || tag === "polyline" || tag === "polygon" || tag === "path";
  }

  function addSvgFocusConnector(node) {
    const connectors = connectorsForText(node);
    const arrowhead = connectors.find(function (connector) {
      return connector.tagName && connector.tagName.toLowerCase() === "polygon";
    });
    for (const connector of connectors) {
      connector.classList.add("asset-focus-connector");
      if (isReverseConnector(connector, arrowhead)) {
        connector.classList.add("asset-focus-connector-reverse");
      }
    }
  }

  function connectorsForText(node) {
    let current = node.previousElementSibling;
    let inspected = 0;
    const connectors = [];
    while (current && inspected < 5 && connectors.length < 2) {
      if (isSvgConnector(current)) {
        connectors.push(current);
      }
      current = current.previousElementSibling;
      inspected += 1;
    }
    return connectors;
  }

  function isReverseConnector(node, arrowhead) {
    const tag = node.tagName.toLowerCase();
    const points = connectorEndpoints(node, tag);
    if (!points) {
      return false;
    }
    if (arrowhead && node !== arrowhead) {
      const arrowCenter = connectorCenter(arrowhead, "polygon");
      if (arrowCenter) {
        const startDistance = distance(points.start, arrowCenter);
        const endDistance = distance(points.end, arrowCenter);
        return startDistance < endDistance;
      }
    }
    const dx = points.end.x - points.start.x;
    const dy = points.end.y - points.start.y;
    if (Math.abs(dx) >= Math.abs(dy)) {
      return dx < 0;
    }
    return dy < 0;
  }

  function connectorEndpoints(node, tag) {
    if (tag === "line") {
      return {
        start: { x: numberAttr(node, "x1"), y: numberAttr(node, "y1") },
        end: { x: numberAttr(node, "x2"), y: numberAttr(node, "y2") },
      };
    }
    if (tag === "polyline" || tag === "polygon") {
      return endpointsFromNumbers((node.getAttribute("points") || "").match(/-?\\d+(?:\\.\\d+)?/g));
    }
    if (tag === "path") {
      return endpointsFromNumbers((node.getAttribute("d") || "").match(/-?\\d+(?:\\.\\d+)?/g));
    }
    return null;
  }

  function endpointsFromNumbers(rawNumbers) {
    if (!rawNumbers || rawNumbers.length < 4) {
      return null;
    }
    const numbers = rawNumbers.map(Number);
    return {
      start: { x: numbers[0], y: numbers[1] },
      end: { x: numbers[numbers.length - 2], y: numbers[numbers.length - 1] },
    };
  }

  function connectorCenter(node, tag) {
    const endpoints = connectorEndpoints(node, tag);
    if (!endpoints) {
      return null;
    }
    return {
      x: (endpoints.start.x + endpoints.end.x) / 2,
      y: (endpoints.start.y + endpoints.end.y) / 2,
    };
  }

  function distance(a, b) {
    const dx = a.x - b.x;
    const dy = a.y - b.y;
    return Math.sqrt(dx * dx + dy * dy);
  }

  function numberAttr(node, name) {
    return Number(node.getAttribute(name) || 0);
  }

  function updateSearch(resetIndex) {
    clearSearch();
    const query = searchInput ? searchInput.value : "";
    if (!query) {
      return;
    }
    if (mode === "diagram") {
      searchDiagram(query);
    } else if (mode === "log") {
      searchLog(query);
    }
    if (!searchMatches.length) {
      if (searchCount) {
        searchCount.textContent = "0";
      }
      return;
    }
    searchIndex = resetIndex ? 0 : Math.max(0, Math.min(searchIndex, searchMatches.length - 1));
    showSearchMatch();
  }

  function searchDiagram(query) {
    const lowerQuery = query.toLowerCase();
    const textNodes = content.querySelectorAll("svg text");
    for (const node of textNodes) {
      if (node.textContent.toLowerCase().includes(lowerQuery)) {
        node.classList.add("asset-search-match");
        searchMatches.push(node);
      }
    }
  }

  function searchLog(query) {
    renderLogView(query, activeFocusTerms);
  }

  function appendSearchParts(parent, text, query) {
    if (!query) {
      parent.appendChild(document.createTextNode(text));
      return;
    }
    const lowerText = text.toLowerCase();
    const lowerQuery = query.toLowerCase();
    let offset = 0;
    while (true) {
      const matchAt = lowerText.indexOf(lowerQuery, offset);
      if (matchAt === -1) {
        break;
      }
      parent.appendChild(document.createTextNode(text.slice(offset, matchAt)));
      const mark = document.createElement("mark");
      mark.className = "asset-search-match";
      mark.textContent = text.slice(matchAt, matchAt + query.length);
      parent.appendChild(mark);
      searchMatches.push(mark);
      offset = matchAt + query.length;
    }
    parent.appendChild(document.createTextNode(text.slice(offset)));
  }

  function renderLogView(query, focusTerms) {
    const pre = content.querySelector(".log-view-text");
    if (!pre) {
      return;
    }
    const sourceText = pre.dataset.sourceText || pre.textContent;
    pre.dataset.sourceText = sourceText;
    const fragment = document.createDocumentFragment();
    const lines = sourceText.split("\\n");
    lines.forEach(function (line, index) {
      if (matchesAnyTerm(line, focusTerms)) {
        const span = document.createElement("span");
        span.className = "asset-focus-line";
        appendSearchParts(span, line, query);
        fragment.appendChild(span);
      } else {
        appendSearchParts(fragment, line, query);
      }
      if (index < lines.length - 1) {
        fragment.appendChild(document.createTextNode("\\n"));
      }
    });
    pre.replaceChildren(fragment);
  }

  function parseNotes(value) {
    if (!value) {
      return [];
    }
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function parseCodeLinks(value) {
    if (!value) {
      return [];
    }
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function applyFocusTerms(terms, notes) {
    clearFocus();
    activeFocusTerms = terms;
    activeNotes = notes || [];
    if (generalViewButton) {
      generalViewButton.hidden = !(activeFocusTerms.length || activeNotes.length);
    }
    if (mode === "diagram") {
      const focused = [];
      const textNodes = content.querySelectorAll("svg text, svg tspan");
      for (const node of textNodes) {
        if (matchesAnyTerm(node.textContent, activeFocusTerms)) {
          node.classList.add("asset-focus-match");
          if (!isDiagramNoteTarget(node, notes || [])) {
            addSvgFocusBox(node);
          }
          addSvgFocusConnector(node);
          focused.push(node);
        }
      }
      addDiagramNotes(notes || [], textNodes);
      if (focused[0]) {
        focused[0].scrollIntoView({ block: "center", inline: "center" });
      }
    } else if (mode === "log") {
      renderLogView(searchInput ? searchInput.value : "", activeFocusTerms);
      const firstLine = content.querySelector(".asset-focus-line");
      if (firstLine) {
        firstLine.scrollIntoView({ block: "center", inline: "nearest" });
      }
    }
  }

  function applyCodeLinks(links) {
    activeCodeLinks = links || [];
    closeCodePopover();
    activeCodeLinkHoverInstance = "";
    activeCodeLinkHoverTarget = "";
    for (const node of content.querySelectorAll(".diagram-code-link-hit-area")) {
      node.remove();
    }
    for (const node of content.querySelectorAll(".diagram-code-link-target, .diagram-code-link-connector, .diagram-code-link-hover, .diagram-code-link-active")) {
      node.classList.remove("diagram-code-link-target", "diagram-code-link-connector", "diagram-code-link-hover", "diagram-code-link-active");
      delete node.dataset.codeLinkTarget;
      delete node.dataset.codeLinkInstance;
    }
    if (mode !== "diagram" || !activeCodeLinks.length) {
      return;
    }
    const textNodes = content.querySelectorAll("svg text, svg tspan");
    let instanceIndex = 0;
    for (const link of activeCodeLinks) {
      const target = String(link.target || "").toLowerCase();
      if (!target) {
        continue;
      }
      for (const node of textNodes) {
        if (!node.textContent.toLowerCase().includes(target)) {
          continue;
        }
        decorateCodeLinkTarget(node, link, "code-link-" + String(instanceIndex));
        instanceIndex += 1;
      }
    }
  }

  function decorateCodeLinkTarget(node, link, instanceKey) {
    node = codeLinkLabelNode(node);
    const targetKey = String(link.target || "");
    const connectors = connectorsForText(node);
    node.classList.add("diagram-code-link-target");
    node.dataset.codeLinkTarget = targetKey;
    node.dataset.codeLinkInstance = instanceKey;
    node.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      activateCodeLink(targetKey, instanceKey);
    });
    attachCodeLinkHover(node, targetKey, instanceKey);
    for (const connector of connectors) {
      connector.classList.add("diagram-code-link-connector");
      connector.dataset.codeLinkTarget = targetKey;
      connector.dataset.codeLinkInstance = instanceKey;
      connector.addEventListener("click", function (event) {
        event.preventDefault();
        event.stopPropagation();
        activateCodeLink(targetKey, instanceKey);
      });
      attachCodeLinkHover(connector, targetKey, instanceKey);
    }
    addCodeLinkHitArea(node, connectors, targetKey, instanceKey);
  }

  function codeLinkLabelNode(node) {
    if (node && node.tagName && node.tagName.toLowerCase() === "tspan" && node.parentElement) {
      return node.parentElement;
    }
    return node;
  }

  function attachCodeLinkHover(node, targetKey, instanceKey) {
    node.dataset.codeLinkTarget = targetKey;
    node.dataset.codeLinkInstance = instanceKey;
  }

  function setCodeLinkHover(targetKey, instanceKey, enabled) {
    for (const node of content.querySelectorAll("[data-code-link-instance]")) {
      if (node.dataset.codeLinkInstance === instanceKey) {
        node.classList.toggle("diagram-code-link-hover", enabled);
      }
    }
    setDiagramNoteHoverForTarget(targetKey, enabled);
  }

  function updateCodeLinkHoverFromPointer(event) {
    if (modal.hidden || mode !== "diagram") {
      clearCodeLinkHover();
      return;
    }
    const pointerTarget = document.elementFromPoint(event.clientX, event.clientY);
    const item = pointerTarget ? pointerTarget.closest("[data-code-link-instance]") : null;
    if (!item || !content.contains(item)) {
      clearCodeLinkHover();
      return;
    }
    const instanceKey = item.dataset.codeLinkInstance || "";
    const targetKey = item.dataset.codeLinkTarget || "";
    if (!instanceKey || instanceKey === activeCodeLinkHoverInstance) {
      return;
    }
    clearCodeLinkHover();
    activeCodeLinkHoverInstance = instanceKey;
    activeCodeLinkHoverTarget = targetKey;
    setCodeLinkHover(targetKey, instanceKey, true);
  }

  function clearCodeLinkHover() {
    if (!activeCodeLinkHoverInstance) {
      return;
    }
    setCodeLinkHover(activeCodeLinkHoverTarget, activeCodeLinkHoverInstance, false);
    activeCodeLinkHoverInstance = "";
    activeCodeLinkHoverTarget = "";
  }

  function setDiagramNoteHoverForTarget(targetKey, enabled) {
    const normalizedTarget = String(targetKey || "").toLowerCase();
    if (!normalizedTarget) {
      return;
    }
    for (const note of content.querySelectorAll("[data-diagram-note-target]")) {
      const noteTarget = String(note.dataset.diagramNoteTarget || "").toLowerCase();
      if (noteTarget && (normalizedTarget.includes(noteTarget) || noteTarget.includes(normalizedTarget))) {
        note.classList.toggle("diagram-note-hover", enabled);
      }
    }
  }

  function addCodeLinkHitArea(labelNode, connectors, targetKey, instanceKey) {
    const svg = labelNode.ownerSVGElement;
    const box = combinedSvgBox([labelNode].concat(connectors));
    if (!svg || !box) {
      return;
    }
    const paddingX = 2;
    const paddingY = 3;
    const hitArea = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    hitArea.setAttribute("class", "diagram-code-link-hit-area");
    hitArea.setAttribute("x", String(box.x - paddingX));
    hitArea.setAttribute("y", String(box.y - paddingY));
    hitArea.setAttribute("width", String(box.width + paddingX * 2));
    hitArea.setAttribute("height", String(box.height + paddingY * 2));
    hitArea.setAttribute("rx", "3");
    hitArea.setAttribute("ry", "3");
    hitArea.dataset.codeLinkTarget = targetKey;
    hitArea.dataset.codeLinkInstance = instanceKey;
    hitArea.addEventListener("click", function (event) {
      event.preventDefault();
      event.stopPropagation();
      activateCodeLink(targetKey, instanceKey);
    });
    attachCodeLinkHover(hitArea, targetKey, instanceKey);
    const parent = labelNode.parentNode || svg;
    parent.insertBefore(hitArea, firstSvgSibling([labelNode].concat(connectors), parent));
  }

  function firstSvgSibling(nodes, parent) {
    const siblings = nodes.filter(function (node) {
      return node && node.parentNode === parent;
    });
    if (!siblings.length) {
      return parent.firstChild;
    }
    return siblings.reduce(function (first, node) {
      if (!first) {
        return node;
      }
      return first.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_PRECEDING ? node : first;
    }, null);
  }

  function combinedSvgBox(nodes) {
    let result = null;
    for (const node of nodes) {
      const box = safeBBox(node);
      if (!box) {
        continue;
      }
      if (!result) {
        result = { x: box.x, y: box.y, width: box.width, height: box.height };
        continue;
      }
      const minX = Math.min(result.x, box.x);
      const minY = Math.min(result.y, box.y);
      const maxX = Math.max(result.x + result.width, box.x + box.width);
      const maxY = Math.max(result.y + result.height, box.y + box.height);
      result = { x: minX, y: minY, width: maxX - minX, height: maxY - minY };
    }
    return result;
  }

  function activateCodeLink(targetKey, instanceKey) {
    const links = activeCodeLinks.filter(function (link) {
      return String(link.target || "") === String(targetKey || "");
    });
    if (!links.length) {
      return;
    }
    markActiveCodeLink(instanceKey);
    renderCodePopover(targetKey, links);
  }

  function markActiveCodeLink(instanceKey) {
    for (const node of content.querySelectorAll(".diagram-code-link-active")) {
      node.classList.remove("diagram-code-link-active");
    }
    for (const node of content.querySelectorAll("[data-code-link-instance]")) {
      if (node.dataset.codeLinkInstance === instanceKey) {
        node.classList.add("diagram-code-link-active");
      }
    }
  }

  function closeCodePopover() {
    const overlay = content.querySelector(".diagram-code-overlay");
    if (overlay) {
      overlay.remove();
    }
    for (const node of content.querySelectorAll(".diagram-code-link-active")) {
      node.classList.remove("diagram-code-link-active");
    }
    for (const node of content.querySelectorAll(".diagram-code-link-hover")) {
      node.classList.remove("diagram-code-link-hover");
    }
    activeCodeLinkHoverInstance = "";
    activeCodeLinkHoverTarget = "";
  }

  function renderCodePopover(targetKey, links) {
    closeExistingCodePopoverOnly();
    const overlay = document.createElement("div");
    overlay.className = "diagram-code-overlay";
    overlay.style.top = content.scrollTop + "px";
    overlay.style.left = content.scrollLeft + "px";
    overlay.style.width = content.clientWidth + "px";
    overlay.style.height = content.clientHeight + "px";
    overlay.addEventListener("click", function (event) {
      if (event.target === overlay) {
        closeCodePopover();
      }
    });
    const popover = document.createElement("section");
    popover.className = "diagram-code-popover";
    popover.setAttribute("aria-label", "Code linked from diagram");
    popover.addEventListener("click", function (event) {
      event.stopPropagation();
    });
    const header = document.createElement("div");
    header.className = "diagram-code-popover-header";
    const heading = document.createElement("span");
    heading.className = "diagram-code-popover-title";
    heading.textContent = targetKey;
    header.appendChild(heading);
    const close = document.createElement("button");
    close.type = "button";
    close.className = "diagram-code-popover-close";
    close.setAttribute("aria-label", "Close linked code");
    close.textContent = "×";
    close.addEventListener("click", closeCodePopover);
    header.appendChild(close);
    popover.appendChild(header);
    const body = document.createElement("div");
    body.className = "diagram-code-popover-body";
    for (const link of links) {
      body.appendChild(createCodeLinkItem(link));
    }
    popover.appendChild(body);
    overlay.appendChild(popover);
    content.appendChild(overlay);
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        centerCodeTarget(popover);
      });
    });
  }

  function centerCodeTarget(popover) {
    const firstTarget = popover.querySelector(".diagram-code-target-line");
    if (!firstTarget) {
      return;
    }
    const codeBox = firstTarget.closest(".diagram-code-link-code");
    if (!codeBox) {
      return;
    }
    const codeBoxRect = codeBox.getBoundingClientRect();
    const targetRect = firstTarget.getBoundingClientRect();
    const targetMiddle = (
      codeBox.scrollTop
      + targetRect.top
      - codeBoxRect.top
      + targetRect.height / 2
    );
    const maxScroll = Math.max(0, codeBox.scrollHeight - codeBox.clientHeight);
    codeBox.scrollTop = Math.min(maxScroll, Math.max(0, targetMiddle - codeBox.clientHeight / 2));
  }

  function closeExistingCodePopoverOnly() {
    const overlay = content.querySelector(".diagram-code-overlay");
    if (overlay) {
      overlay.remove();
    }
  }

  function createCodeLinkItem(link) {
    const item = document.createElement("div");
    item.className = "diagram-code-link-item";
    const titleNode = document.createElement("span");
    titleNode.className = "diagram-code-link-title";
    titleNode.textContent = String(link.title || link.target || "Code");
    item.appendChild(titleNode);
    const location = document.createElement("span");
    location.className = "diagram-code-link-location";
    location.textContent = String(link.file || "") + ":" + String(link.line || "");
    item.appendChild(location);
    const code = document.createElement("code");
    code.className = "diagram-code-link-code";
    renderDiffFileContext(code, link);
    item.appendChild(code);
    return item;
  }

  function renderDiffFileContext(parent, link) {
    const rows = diffFileRowsForLink(link);
    if (!rows.length) {
      parent.textContent = "Target file is not present in this rendered diff.";
      return;
    }
    const targetRange = targetRangeForLink(link);
    const targetLine = Number(link.line);
    rows.forEach(function (row, index) {
      const line = Number(row.dataset.newLine || 0);
      const span = document.createElement("span");
      span.className = "diagram-code-line";
      if (targetRange && line >= targetRange.start && line <= targetRange.end) {
        span.classList.add("diagram-code-context-line");
      }
      if (Number.isFinite(targetLine) && line === targetLine) {
        span.classList.add("diagram-code-target-line");
      }
      const newLine = row.dataset.newLine || "";
      const code = row.querySelector(".code");
      span.textContent = String(newLine).padStart(5, " ") + "  " + (code ? code.textContent : "");
      parent.appendChild(span);
    });
  }

  function diffFileRowsForLink(link) {
    const filePath = String(link.file || "");
    if (!filePath) {
      return [];
    }
    return Array.from(document.querySelectorAll("tr[data-file]")).filter(function (row) {
      return row.dataset.file === filePath && row.dataset.newLine;
    });
  }

  function targetRangeForLink(link) {
    const filePath = String(link.file || "");
    const startLine = Number((link.range && link.range.start) || link.line);
    const endLine = Number((link.range && link.range.end) || link.line);
    if (!filePath || !Number.isFinite(startLine) || !Number.isFinite(endLine)) {
      return null;
    }
    return { start: Math.min(startLine, endLine), end: Math.max(startLine, endLine) };
  }

  function isDiagramNoteTarget(node, notes) {
    return notes.some(function (note) {
      const target = String(note.target || "").toLowerCase();
      return target && node.textContent.toLowerCase().includes(target);
    });
  }

  function addDiagramNotes(notes, textNodes) {
    if (!notes.length) {
      return;
    }
    const svg = content.querySelector("svg");
    if (!svg) {
      return;
    }
    const layer = document.createElementNS("http://www.w3.org/2000/svg", "g");
    layer.setAttribute("class", "diagram-note-layer");
    svg.appendChild(layer);
    const viewBox = svg.viewBox && svg.viewBox.baseVal && svg.viewBox.baseVal.width
      ? svg.viewBox.baseVal
      : { x: 0, y: 0, width: Number(svg.getAttribute("width")) || 900, height: Number(svg.getAttribute("height")) || 900 };
    notes.forEach(function (note, index) {
      const target = findNoteTarget(textNodes, note.target || "");
      if (!target) {
        return;
      }
      const targetBox = safeBBox(target);
      if (!targetBox) {
        return;
      }
      const noteWidth = Math.min(320, Math.max(180, String(note.text || "").length * 4.2 + 24));
      const noteLines = estimateSvgTextLines(String(note.text || ""), noteWidth - 20);
      const noteHeight = Math.max(44, 18 + noteLines * 15);
      const connectors = connectorsForText(target);
      const anchor = labelRightAnchor(targetBox);
      const marker = diagramNoteMarkerPosition(viewBox, anchor);
      const position = diagramNotePosition(note, viewBox, marker, noteWidth, noteHeight, index);
      const x = position.x;
      const y = position.y;
      const group = createDiagramNote(note, x, y, noteWidth, noteHeight, marker, connectors.concat([target]));
      layer.appendChild(group);
      raiseFocusTarget(target, connectors);
    });
  }

  function diagramNoteMarkerPosition(viewBox, anchor) {
    const margin = 18;
    return {
      x: clamp(anchor.x + 18, viewBox.x + margin, viewBox.x + viewBox.width - margin),
      y: clamp(anchor.y, viewBox.y + margin, viewBox.y + viewBox.height - margin),
    };
  }

  function diagramNotePosition(note, viewBox, marker, width, height, index) {
    const margin = 24;
    const maxXOffset = 360;
    const maxYOffset = 220;
    const minX = viewBox.x + margin;
    const maxX = viewBox.x + viewBox.width - width - margin;
    const minY = viewBox.y + margin;
    const maxY = viewBox.y + viewBox.height - height - margin;
    if (Number.isFinite(note.x) && Number.isFinite(note.y)) {
      return {
        x: clamp(Number(note.x), minX, maxX),
        y: clamp(Number(note.y), minY, maxY),
      };
    }
    const rightX = clamp(marker.x + 30, minX, Math.min(maxX, marker.x + maxXOffset));
    const leftX = clamp(marker.x - width - 30, Math.max(minX, marker.x - maxXOffset), maxX);
    const hasRoomRight = rightX >= marker.x + 18;
    const x = hasRoomRight ? rightX : leftX;
    const idealY = marker.y - height / 2 + index * 4;
    const y = clamp(idealY, Math.max(minY, marker.y - maxYOffset), Math.min(maxY, marker.y + maxYOffset));
    return { x, y };
  }

  function clamp(value, min, max) {
    if (max < min) {
      return min;
    }
    return Math.min(max, Math.max(min, value));
  }

  function findNoteTarget(textNodes, targetText) {
    const lowerTarget = String(targetText).toLowerCase();
    for (const node of textNodes) {
      if (node.textContent.toLowerCase().includes(lowerTarget)) {
        return node;
      }
    }
    return null;
  }

  function labelRightAnchor(box) {
    return {
      x: box.x + box.width + 6,
      y: box.y + box.height / 2,
    };
  }

  function createDiagramNote(note, x, y, width, height, markerPoint, relatedNodes) {
    const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
    group.setAttribute("class", "diagram-note-hotspot");
    group.dataset.diagramNoteTarget = String(note.target || "");
    for (const eventName of ["click", "dblclick", "mousedown", "pointerdown"]) {
      group.addEventListener(eventName, stopDiagramNoteEvent);
    }
    const markerX = markerPoint.x;
    const markerY = markerPoint.y;
    const marker = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    marker.setAttribute("class", "diagram-note-marker");
    marker.setAttribute("cx", String(markerX));
    marker.setAttribute("cy", String(markerY));
    marker.setAttribute("r", "9");
    group.appendChild(marker);
    const markerText = document.createElementNS("http://www.w3.org/2000/svg", "text");
    markerText.setAttribute("class", "diagram-note-marker-text");
    markerText.setAttribute("x", String(markerX));
    markerText.setAttribute("y", String(markerY + 0.5));
    markerText.textContent = "i";
    group.appendChild(markerText);
    const panel = document.createElementNS("http://www.w3.org/2000/svg", "g");
    panel.setAttribute("class", "diagram-note-panel");
    const link = document.createElementNS("http://www.w3.org/2000/svg", "path");
    link.setAttribute("class", "diagram-note-link");
    link.setAttribute("d", noteLinkPath(markerX, markerY, x, y + height / 2));
    panel.appendChild(link);
    const rect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    rect.setAttribute("class", "diagram-note-box");
    rect.setAttribute("x", String(x));
    rect.setAttribute("y", String(y));
    rect.setAttribute("width", String(width));
    rect.setAttribute("height", String(height));
    panel.appendChild(rect);
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("class", "diagram-note-text");
    text.setAttribute("x", String(x + 10));
    text.setAttribute("y", String(y + 18));
    wrapSvgText(text, String(note.text || ""), width - 20);
    panel.appendChild(text);
    group.appendChild(panel);
    group.addEventListener("mouseenter", function () {
      group.classList.add("diagram-note-hover");
      for (const node of relatedNodes) {
        node.classList.add("asset-focus-related-hover");
      }
    });
    group.addEventListener("mouseleave", function () {
      group.classList.remove("diagram-note-hover");
      for (const node of relatedNodes) {
        node.classList.remove("asset-focus-related-hover");
      }
    });
    for (const node of relatedNodes) {
      node.addEventListener("mouseenter", function () {
        group.classList.add("diagram-note-hover");
        for (const item of relatedNodes) {
          item.classList.add("asset-focus-related-hover");
        }
      });
      node.addEventListener("mouseleave", function () {
        group.classList.remove("diagram-note-hover");
        for (const item of relatedNodes) {
          item.classList.remove("asset-focus-related-hover");
        }
      });
    }
    return group;
  }

  function raiseFocusTarget(target, connectors) {
    const parent = target.parentNode;
    if (!parent) {
      return;
    }
    for (const candidate of Array.from(parent.querySelectorAll(".asset-focus-box"))) {
      const box = safeBBox(candidate);
      const targetBox = safeBBox(target);
      if (box && targetBox && boxesOverlap(box, targetBox)) {
        parent.appendChild(candidate);
        break;
      }
    }
    for (const connector of connectors) {
      if (connector.parentNode === parent) {
        parent.appendChild(connector);
      }
    }
    parent.appendChild(target);
  }

  function boxesOverlap(a, b) {
    return (
      a.x <= b.x + b.width &&
      a.x + a.width >= b.x &&
      a.y <= b.y + b.height &&
      a.y + a.height >= b.y
    );
  }

  function stopDiagramNoteEvent(event) {
    event.preventDefault();
    event.stopPropagation();
  }

  function noteLinkPath(x1, y1, x2, y2) {
    return [
      "M", x1, y1,
      "L", x2, y2,
    ].join(" ");
  }

  function estimateSvgTextLines(text, maxWidth) {
    const words = text.split(/\\s+/).filter(Boolean);
    let line = "";
    let lines = 0;
    for (const word of words) {
      const next = line ? line + " " + word : word;
      if (next.length * 6.4 > maxWidth && line) {
        lines += 1;
        line = word;
      } else {
        line = next;
      }
    }
    return lines + (line ? 1 : 0);
  }

  function wrapSvgText(textNode, text, maxWidth) {
    const words = text.split(/\\s+/);
    let line = "";
    let lineNo = 0;
    for (const word of words) {
      const next = line ? line + " " + word : word;
      if (next.length * 6.4 > maxWidth && line) {
        appendTspan(textNode, line, lineNo);
        line = word;
        lineNo += 1;
      } else {
        line = next;
      }
    }
    if (line) {
      appendTspan(textNode, line, lineNo);
    }
  }

  function appendTspan(textNode, text, lineNo) {
    const tspan = document.createElementNS("http://www.w3.org/2000/svg", "tspan");
    tspan.setAttribute("x", textNode.getAttribute("x"));
    tspan.setAttribute("dy", lineNo === 0 ? "0" : "15");
    tspan.textContent = text;
    textNode.appendChild(tspan);
  }

  function safeBBox(node) {
    try {
      return node.getBBox();
    } catch (error) {
      return null;
    }
  }

  function showSearchMatch() {
    for (const node of searchMatches) {
      node.classList.remove("asset-search-current");
    }
    const current = searchMatches[searchIndex];
    if (!current) {
      return;
    }
    current.classList.add("asset-search-current");
    current.scrollIntoView({ block: "center", inline: "center" });
    if (searchCount) {
      searchCount.textContent = (searchIndex + 1) + "/" + searchMatches.length;
    }
  }

  function moveSearch(delta) {
    if (!searchMatches.length) {
      updateSearch(true);
      return;
    }
    searchIndex = (searchIndex + delta + searchMatches.length) % searchMatches.length;
    showSearchMatch();
  }

  function openTemplate(prefix, id, nextMode, focusTerms, notes) {
    const template = document.getElementById(prefix + "-template-" + id);
    if (!template) {
      return;
    }
    title.textContent = template.dataset.title || "Diagram";
    content.innerHTML = "";
    const stage = document.createElement("div");
    stage.className = "diagram-zoom-stage";
    stage.appendChild(template.content.cloneNode(true));
    content.appendChild(stage);
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    setMode(nextMode);
    if (searchInput) {
      searchInput.value = "";
    }
    setScale(1);
    applyFocusTerms(focusTerms || [], notes || []);
    applyCodeLinks(nextMode === "diagram" ? parseCodeLinks(template.dataset.codeLinks) : []);
    if (nextMode === "log" && searchInput) {
      searchInput.focus();
    }
  }

  function openDiagram(id, focusTerms, notes) {
    openTemplate("diagram", id, "diagram", focusTerms, notes);
  }

  function openLog(id, focusTerms) {
    openTemplate("log", id, "log", focusTerms);
  }

  function closeDiagram() {
    modal.hidden = true;
    content.innerHTML = "";
    document.body.style.overflow = "";
    scale = 1;
    setMode("");
    activeFocusTerms = [];
    activeNotes = [];
    activeCodeLinks = [];
    closeCodePopover();
    clearSearch();
  }

  document.addEventListener("click", function (event) {
    const preview = event.target.closest("[data-diagram-id]");
    if (preview) {
      openDiagram(preview.dataset.diagramId, parseFocus(preview.dataset.diagramFocus), parseNotes(preview.dataset.diagramNotes));
      return;
    }
    const logPreview = event.target.closest("[data-log-id]");
    if (logPreview) {
      openLog(logPreview.dataset.logId, parseFocus(logPreview.dataset.logFocus));
      return;
    }
    if (event.target.closest("[data-diagram-close]")) {
      closeDiagram();
      return;
    }
    const zoom = event.target.closest("[data-diagram-zoom]");
    if (zoom) {
      const action = zoom.dataset.diagramZoom;
      if (action === "in") {
        setScale(scale + 0.25);
      } else if (action === "out") {
        setScale(scale - 0.25);
      } else {
        setScale(1);
      }
      return;
    }
    const search = event.target.closest("[data-diagram-search]");
    if (search) {
      moveSearch(search.dataset.diagramSearch === "prev" ? -1 : 1);
      return;
    }
    if (event.target.closest("[data-diagram-general]")) {
      closeCodePopover();
      applyFocusTerms([], []);
      return;
    }
    if (event.target.closest(".diagram-code-popover")) {
      event.stopPropagation();
      return;
    }
  });

  document.addEventListener("keydown", function (event) {
    if (modal.hidden) {
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "f") {
      event.preventDefault();
      if (searchInput) {
        searchInput.focus();
        searchInput.select();
      }
      return;
    }
    if (event.key === "Enter" && document.activeElement === searchInput) {
      event.preventDefault();
      moveSearch(event.shiftKey ? -1 : 1);
      return;
    }
    if (event.key === "Escape") {
      if (content.querySelector(".diagram-code-overlay")) {
        closeCodePopover();
        return;
      }
      closeDiagram();
    }
  });

  document.addEventListener("pointermove", function (event) {
    updateCodeLinkHoverFromPointer(event);
  });

  document.addEventListener("pointerleave", function () {
    clearCodeLinkHover();
  });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
      clearCodeLinkHover();
    }
  });

  if (searchInput) {
    searchInput.addEventListener("input", function () {
      updateSearch(true);
    });
  }

  content.addEventListener("wheel", function (event) {
    clearCodeLinkHover();
    if (!event.ctrlKey || modal.hidden || mode !== "diagram") {
      return;
    }
    event.preventDefault();
    const step = event.deltaY < 0 ? 0.1 : -0.1;
    setScale(scale + step);
  }, { passive: false });

  content.addEventListener("pointerdown", function (event) {
    if (modal.hidden || mode !== "diagram" || event.button !== 0) {
      return;
    }
    if (event.target.closest("button, input")) {
      return;
    }
    if (event.target.closest(".diagram-code-link-target, .diagram-code-link-connector, .diagram-code-link-hit-area, .diagram-note-hotspot, .diagram-code-overlay")) {
      return;
    }
    clearCodeLinkHover();
    isPanning = true;
    panStartX = event.clientX;
    panStartY = event.clientY;
    panStartLeft = content.scrollLeft;
    panStartTop = content.scrollTop;
    content.classList.add("is-panning");
    content.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  content.addEventListener("pointermove", function (event) {
    if (!isPanning) {
      return;
    }
    content.scrollLeft = panStartLeft - (event.clientX - panStartX);
    content.scrollTop = panStartTop - (event.clientY - panStartY);
  });

  function stopPanning(event) {
    if (!isPanning) {
      return;
    }
    isPanning = false;
    content.classList.remove("is-panning");
    if (event && typeof event.pointerId === "number") {
      content.releasePointerCapture(event.pointerId);
    }
  }

  content.addEventListener("pointerup", stopPanning);
  content.addEventListener("pointercancel", stopPanning);
}());
</script>
"""


def _parse_rev_range(rev_range: str) -> tuple[str, str]:
    if "..." in rev_range:
        base, head = rev_range.split("...", 1)
    elif ".." in rev_range:
        base, head = rev_range.split("..", 1)
    else:
        raise DiffReportError("--range must use '..' or '...', for example HEAD^..HEAD")
    if not base or not head:
        raise DiffReportError("--range must include both base and head revisions")
    return base, head


def _git(repo_path: Path, args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(repo_path), *args], text=True, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as error:
        message = error.stderr.strip() or str(error)
        raise DiffReportError(message) from error


def _commit_message_from_patch(diff_text: str) -> tuple[str | None, str | None]:
    message_lines: list[str] = []
    in_message = False

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            break
        if line.startswith("    "):
            in_message = True
            message_lines.append(line[4:])
        elif in_message and line == "":
            message_lines.append("")
        elif in_message:
            break

    while message_lines and message_lines[0] == "":
        message_lines.pop(0)
    while message_lines and message_lines[-1] == "":
        message_lines.pop()

    if not message_lines:
        return None, None

    message = "\n".join(message_lines)
    subject = next((line for line in message_lines if line), None)
    return subject, message


def _diff_files(diff_text: str) -> list[str]:
    files: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            files.append(_file_from_diff_header(line))
    return files


def _file_from_diff_header(line: str) -> str:
    match = re.match(r"diff --git a/(.*?) b/(.*)", line)
    if not match:
        return line
    return match.group(2)


def _is_diff_metadata(line: str) -> bool:
    prefixes = (
        "--- ",
        "+++ ",
        "index ",
        "new file",
        "deleted file",
        "similarity ",
        "rename ",
        "old mode",
        "new mode",
    )
    return line.startswith(prefixes)


def _required(payload: dict[str, Any], key: str) -> Any:
    if key not in payload:
        raise DiffReportError(f"comments inline entry is missing required key: {key}")
    return payload[key]


def _focus_terms(raw: Any, *, field: str) -> tuple[str, ...]:
    if raw in (None, "", []):
        return ()
    if isinstance(raw, str):
        return (raw,)
    if not isinstance(raw, (list, tuple)):
        raise DiffReportError(f"comments {field} must be a string or list of strings")
    return tuple(str(item) for item in raw if str(item))


def _diagram_notes(raw: Any) -> tuple[dict[str, Any], ...]:
    if raw in (None, "", [], ()):
        return ()
    if not isinstance(raw, list):
        raise DiffReportError("comments diagram_notes must be a list of objects")
    notes: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise DiffReportError("comments diagram_notes entries must be objects")
        text = str(_required(item, "text"))
        note: dict[str, Any] = {"text": text}
        if "target" in item:
            note["target"] = str(item["target"])
        for key in ("x", "y", "dx", "dy"):
            if key in item:
                note[key] = float(item[key])
        if "target" not in note and ("x" not in note or "y" not in note):
            raise DiffReportError("diagram_notes entries must include target or both x and y")
        notes.append(note)
    return tuple(notes)


def _maybe_code(value: str | None) -> str:
    if not value:
        return "n/a"
    return f"<code>{_esc(value)}</code>"


def _log_excerpt(text: str, *, max_lines: int = 12, max_chars: int = 1400) -> str:
    excerpt = "\n".join(text.splitlines()[:max_lines])
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars].rstrip()
    if excerpt != text:
        excerpt = f"{excerpt}\n..."
    return excerpt


def _focus_attr(name: str, terms: tuple[str, ...]) -> str:
    if not terms:
        return ""
    payload = json.dumps(list(terms), ensure_ascii=False)
    return f' {name}="{_esc(payload)}"'


def _json_attr(name: str, value: object) -> str:
    if not value:
        return ""
    payload = json.dumps(value, ensure_ascii=False)
    return f' {name}="{_esc(payload)}"'


def _anchor(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value)


def _comment_anchor(file_path: str, line: int) -> str:
    return f"comment-{_anchor(file_path)}-{line}"


def _line_anchor(file_path: str, line: int) -> str:
    return f"line-{_anchor(file_path)}-{line}"


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)
