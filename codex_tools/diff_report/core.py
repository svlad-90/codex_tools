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


@dataclass(frozen=True)
class ReviewComments:
    file_comments: dict[str, str]
    inline_comments: dict[tuple[str, int], tuple[InlineComment, ...]]
    summary: str | None = None


@dataclass(frozen=True)
class DiffSource:
    diff_text: str
    stat_text: str
    label: str
    commit: str | None = None
    subject: str | None = None


class DiffReportError(ValueError):
    pass


def compact_help() -> str:
    return "\n".join(
        [
            "diff_report --repo <git_repo> --range HEAD^..HEAD --output report.html [--comments comments.json]",
            "diff_report --diff-file diff.patch --output report.html [--comments comments.json]",
            "",
            "comments.json schema:",
            "{",
            '  "summary": "optional markdown-free text",',
            '  "files": {"path/to/file.py": "file-level comment"},',
            '  "inline": [',
            '    {"file": "path/to/file.py", "line": 42, "body": "comment", "title": "optional"}',
            "  ]",
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
) -> None:
    source = _load_diff_source(repo_path, rev_range, diff_file, context)
    comments = _load_comments(comments_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_html_report(title, source, comments), encoding="utf-8")


def render_html_report(title: str, source: DiffSource, comments: ReviewComments) -> str:
    files = _diff_files(source.diff_text)
    comment_count = _comment_count(comments)
    parts: list[str] = []
    parts.append(_html_header(title))
    parts.append(
        f"""
<main>
  <header>
    <h1>{_esc(title)}</h1>
    <p>GitHub-style unified diff report with optional inline review comments.</p>
    <p><strong>{comment_count}</strong> review comments loaded.</p>
    <div class="meta">
      <div><span class="label">Diff source</span><code>{_esc(source.label)}</code></div>
      <div><span class="label">Commit</span>{_maybe_code(source.commit)}</div>
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
    if comment_count:
        parts.append(_render_comments_index(comments))
    parts.append('  <section><h2>Changed Files</h2><div class="toc">\n')
    for file_path in files:
        parts.append(f'    <a href="#{_anchor(file_path)}">{_esc(file_path)}</a>\n')
    parts.append(f'  </div><pre class="stat">{_esc(source.stat_text)}</pre></section>\n')
    parts.append(_render_diff(source.diff_text, comments))
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
            parts.append(
                f'      <li><a href="#{_comment_anchor(comment.file_path, comment.line)}">'
                f'{_esc(comment.file_path)}:{comment.line}</a> '
                f'<strong>{_esc(comment.title)}</strong>: {_esc(comment.body)}</li>\n'
            )
        parts.append("    </ol>\n")
    parts.append("  </section>\n")
    return "".join(parts)


def _load_diff_source(
    repo_path: Path | None,
    rev_range: str,
    diff_file: Path | None,
    context: int,
) -> DiffSource:
    if diff_file is not None:
        return DiffSource(
            diff_text=diff_file.read_text(encoding="utf-8"),
            stat_text="Loaded from diff file; git stat is unavailable.",
            label=str(diff_file),
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
    return DiffSource(
        diff_text=diff_text,
        stat_text=stat_text,
        label=f"{repo_path} {base}..{head}",
        commit=commit,
        subject=subject,
    )


def _load_comments(comments_file: Path | None) -> ReviewComments:
    if comments_file is None:
        return ReviewComments(file_comments={}, inline_comments={})
    payload = json.loads(comments_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise DiffReportError("Comments JSON must be an object")

    raw_files = payload.get("files", {})
    if not isinstance(raw_files, dict):
        raise DiffReportError("comments.files must be an object")
    file_comments = {str(path): str(body) for path, body in raw_files.items()}

    grouped: dict[tuple[str, int], list[InlineComment]] = {}
    raw_inline = payload.get("inline", [])
    if not isinstance(raw_inline, list):
        raise DiffReportError("comments.inline must be a list")
    for item in raw_inline:
        if not isinstance(item, dict):
            raise DiffReportError("comments.inline entries must be objects")
        file_path = str(_required(item, "file"))
        line = int(_required(item, "line"))
        body = str(_required(item, "body"))
        title = str(item.get("title", "Review comment"))
        grouped.setdefault((file_path, line), []).append(
            InlineComment(file_path=file_path, line=line, body=body, title=title)
        )
    return ReviewComments(
        file_comments=file_comments,
        inline_comments={key: tuple(value) for key, value in grouped.items()},
        summary=str(payload["summary"]) if "summary" in payload else None,
    )


def _render_diff(diff_text: str, comments: ReviewComments) -> str:
    parts: list[str] = []
    current_file: str | None = None
    old_no: int | None = None
    new_no: int | None = None
    table_open = False

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
            parts.append(f'  <article class="file" id="{_anchor(current_file)}">\n')
            parts.append(f'    <div class="file-header">{_esc(current_file)}</div>\n')
            if current_file in comments.file_comments:
                parts.append(
                    f'    <div class="file-comment"><strong>File review note:</strong> '
                    f'{_esc(comments.file_comments[current_file])}</div>\n'
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
            parts.append(_diff_row("add", "", str(new_no), raw_line))
            parts.append(_render_inline_comments(comments, current_file, line_no))
            new_no += 1
        elif raw_line.startswith("-") and not raw_line.startswith("---"):
            parts.append(_diff_row("del", str(old_no), "", raw_line))
            old_no += 1
        else:
            line_no = new_no
            parts.append(_diff_row("ctx", str(old_no), str(new_no), raw_line))
            parts.append(_render_inline_comments(comments, current_file, line_no))
            old_no += 1
            new_no += 1

    close_file()
    return "".join(parts)


def _render_inline_comments(comments: ReviewComments, file_path: str, line: int) -> str:
    rendered: list[str] = []
    for comment in comments.inline_comments.get((file_path, line), ()):
        rendered.append(
            '      <tr class="comment-row"><td colspan="3">'
            f'<div class="review-comment" id="{_comment_anchor(file_path, line)}">'
            f'<div class="title">{_esc(comment.title)} on {_esc(file_path)}:{line}</div>'
            f'<div class="body">{_esc(comment.body)}</div>'
            "</div></td></tr>\n"
        )
    return "".join(rendered)


def _diff_row(kind: str, old_no: str, new_no: str, text: str) -> str:
    return (
        f'      <tr class="{kind}"><td class="num">{_esc(old_no)}</td>'
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
    tr.comment-row td {{ background: #fff; padding: 0 !important; }}
    .review-comment {{ margin: 6px 12px 8px 124px; border: 1px solid var(--comment-border); background: var(--comment-bg); border-radius: 6px; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .review-comment .title {{ padding: 8px 10px; font-weight: 700; border-bottom: 1px solid rgba(212,167,44,.45); }}
    .review-comment .body {{ padding: 9px 10px; }}
  </style>
</head>
<body>
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


def _maybe_code(value: str | None) -> str:
    if not value:
        return "n/a"
    return f"<code>{_esc(value)}</code>"


def _anchor(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value)


def _comment_anchor(file_path: str, line: int) -> str:
    return f"comment-{_anchor(file_path)}-{line}"


def _esc(value: object) -> str:
    return html.escape(str(value), quote=False)
