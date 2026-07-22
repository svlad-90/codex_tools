from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    from .core import DiffReportError, compact_help, generate_report

    parser = argparse.ArgumentParser(
        description="Generate a GitHub-style HTML diff report with review comments.",
    )
    parser.add_argument("--repo", help="Git repository path. Required unless --diff-file is used.")
    parser.add_argument(
        "--range",
        dest="rev_range",
        default="HEAD^..HEAD",
        help="Git revision range to diff, for example HEAD^..HEAD or BASE..HEAD.",
    )
    parser.add_argument("--diff-file", help="Read unified git diff from this file instead of running git.")
    parser.add_argument("--comments", help="JSON file with file-level and inline review comments.")
    parser.add_argument("--output", help="HTML report output path.")
    parser.add_argument("--title", default="PR Diff Review", help="Report title.")
    parser.add_argument("--context", type=int, default=80, help="Git diff context lines.")
    parser.add_argument(
        "--refresh-targets",
        action="store_true",
        help=(
            "Refresh target anchors in the same-basename comments JSON before "
            "rendering self-contained HTML."
        ),
    )
    parser.add_argument(
        "--display-label",
        help="Human-facing diff source label, for example 'Commit 01'.",
    )
    parser.add_argument("--help-compact", action="store_true", help="Print compact CLI synopsis.")

    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    if args.help_compact:
        print(compact_help())
        return 0
    if not args.output:
        parser.error("--output is required unless --help-compact is used")

    try:
        output = _resolve_path(args.output)
        repo = _resolve_path(args.repo) if args.repo else None
        diff_file = _resolve_path(args.diff_file) if args.diff_file else None
        comments_file = _resolve_path(args.comments) if args.comments else None
        generate_report(
            output_path=output,
            title=args.title,
            repo_path=repo,
            rev_range=args.rev_range,
            diff_file=diff_file,
            comments_file=comments_file,
            context=args.context,
            display_label=args.display_label,
            refresh_targets=args.refresh_targets,
        )
        print(str(output))
        return 0
    except (DiffReportError, ValueError, OSError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 1


def _resolve_path(path_text: str | None) -> Path | None:
    if path_text is None:
        return None
    path = Path(path_text)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return path
