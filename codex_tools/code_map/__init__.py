from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from .core import (
        apply_batch_edits,
        CodeMapEditError,
        add_import_statement,
        render_batch_edit_result,
        render_batch_edit_result_json,
        build_facade_audit,
        build_protocol_audit,
        insert_after_symbol,
        insert_before_symbol,
        parse_check,
        render_code_map_json,
        compact_help,
        render_edit_result,
        render_edit_result_json,
        render_error_json,
        render_parse_check,
        render_parse_check_json,
        render_class_diagram,
        render_code_map,
        render_facade_audit,
        render_facade_audit_json,
        render_protocol_audit,
        render_protocol_audit_json,
        render_symbol_snapshot,
        render_symbol_snapshot_json,
        replace_symbol,
        replace_symbol_body,
    )

    effective_argv = list(sys.argv[1:] if argv is None else argv)
    known_commands = {
        "help",
        "map",
        "class-diagram",
        "facade-audit",
        "protocol-audit",
        "symbol-get",
        "replace-symbol",
        "replace-symbol-body",
        "insert-before-symbol",
        "insert-after-symbol",
        "batch",
        "imports-add",
        "parse-check",
    }
    if effective_argv and effective_argv[0] not in known_commands and not effective_argv[0].startswith("-"):
        effective_argv = ["map", *effective_argv]

    parser = argparse.ArgumentParser(description="Print AST maps and generate PlantUML class diagrams.")
    subparsers = parser.add_subparsers(dest="command")

    help_parser = subparsers.add_parser("help", help="Print compact CLI synopsis.")
    help_parser.set_defaults(handler=lambda _args: _print_help(compact_help()))

    map_parser = subparsers.add_parser("map", help="Print class/function map for a Python file.")
    map_parser.add_argument("file_path")
    map_parser.add_argument("--json", action="store_true")
    map_parser.set_defaults(handler=lambda args: _render_code_map(args, render_code_map, render_code_map_json))

    diagram_parser = subparsers.add_parser("class-diagram", help="Generate PlantUML class diagram from Python sources.")
    diagram_parser.add_argument("target_path")
    diagram_parser.add_argument("output", nargs="?")
    diagram_parser.set_defaults(handler=lambda args: _render_class_diagram(args, render_class_diagram))

    audit_parser = subparsers.add_parser(
        "facade-audit",
        help="Audit a class facade surface, wrapper methods, and caller roots.",
    )
    audit_parser.add_argument("file_path")
    audit_parser.add_argument("--symbol", required=True)
    audit_parser.add_argument("--callers", nargs="+", required=True)
    audit_parser.add_argument("--json", action="store_true")
    audit_parser.add_argument("--include-private", action="store_true")
    audit_parser.set_defaults(
        handler=lambda args: _render_facade_audit(
            args,
            build_facade_audit,
            render_facade_audit,
            render_facade_audit_json,
        )
    )

    protocol_parser = subparsers.add_parser(
        "protocol-audit",
        help="Audit protocol/bridge surfaces, GameSession mirrors, and feature owner mixes.",
    )
    protocol_parser.add_argument("target_path")
    protocol_parser.add_argument("--symbol")
    protocol_parser.add_argument("--json", action="store_true")
    protocol_parser.add_argument("--include-private", action="store_true")
    protocol_parser.add_argument("--facade-file")
    protocol_parser.add_argument("--facade-symbol", default="GameSession")
    protocol_parser.set_defaults(
        handler=lambda args: _render_protocol_audit(
            args,
            build_protocol_audit,
            render_protocol_audit,
            render_protocol_audit_json,
        )
    )

    symbol_parser = subparsers.add_parser(
        "symbol-get",
        help="Resolve one symbol span and hashes for guarded edits.",
    )
    symbol_parser.add_argument("file_path")
    symbol_parser.add_argument("--symbol", required=True)
    symbol_parser.add_argument("--json", action="store_true")
    symbol_parser.set_defaults(
        handler=lambda args: _render_symbol_snapshot(
            args,
            render_symbol_snapshot,
            render_symbol_snapshot_json,
        )
    )

    replace_parser = subparsers.add_parser(
        "replace-symbol",
        help="Replace one symbol node when the expected node hash still matches.",
    )
    replace_parser.add_argument("file_path")
    replace_parser.add_argument("--symbol", required=True)
    replace_parser.add_argument("--expect-hash", required=True)
    replace_group = replace_parser.add_mutually_exclusive_group(required=True)
    replace_group.add_argument("--replacement-env")
    replace_group.add_argument("--replacement-file")
    replace_group.add_argument("--replacement-text")
    replace_group.add_argument("--replacement-stdin", action="store_true")
    replace_parser.add_argument("--check-only", action="store_true")
    replace_parser.add_argument("--json", action="store_true")
    replace_parser.set_defaults(
        handler=lambda args: _apply_symbol_edit_command(
            args,
            replace_symbol,
            render_edit_result,
            render_edit_result_json,
            env_arg="replacement_env",
            file_arg="replacement_file",
            text_arg="replacement_text",
            stdin_arg="replacement_stdin",
        )
    )

    replace_body_parser = subparsers.add_parser(
        "replace-symbol-body",
        help="Replace one symbol body when the expected body hash still matches.",
    )
    replace_body_parser.add_argument("file_path")
    replace_body_parser.add_argument("--symbol", required=True)
    replace_body_parser.add_argument("--expect-hash", required=True)
    replace_body_group = replace_body_parser.add_mutually_exclusive_group(required=True)
    replace_body_group.add_argument("--replacement-env")
    replace_body_group.add_argument("--replacement-file")
    replace_body_group.add_argument("--replacement-text")
    replace_body_group.add_argument("--replacement-stdin", action="store_true")
    replace_body_parser.add_argument("--check-only", action="store_true")
    replace_body_parser.add_argument("--json", action="store_true")
    replace_body_parser.set_defaults(
        handler=lambda args: _apply_symbol_edit_command(
            args,
            replace_symbol_body,
            render_edit_result,
            render_edit_result_json,
            env_arg="replacement_env",
            file_arg="replacement_file",
            text_arg="replacement_text",
            stdin_arg="replacement_stdin",
        )
    )

    insert_before_parser = subparsers.add_parser(
        "insert-before-symbol",
        help="Insert a sibling block before one anchor symbol when the anchor hash still matches.",
    )
    insert_before_parser.add_argument("file_path")
    insert_before_parser.add_argument("--symbol", required=True)
    insert_before_parser.add_argument("--expect-hash", required=True)
    insert_before_group = insert_before_parser.add_mutually_exclusive_group(required=True)
    insert_before_group.add_argument("--snippet-env")
    insert_before_group.add_argument("--snippet-file")
    insert_before_group.add_argument("--snippet-text")
    insert_before_group.add_argument("--snippet-stdin", action="store_true")
    insert_before_parser.add_argument("--check-only", action="store_true")
    insert_before_parser.add_argument("--json", action="store_true")
    insert_before_parser.set_defaults(
        handler=lambda args: _apply_symbol_edit_command(
            args,
            insert_before_symbol,
            render_edit_result,
            render_edit_result_json,
            env_arg="snippet_env",
            file_arg="snippet_file",
            text_arg="snippet_text",
            stdin_arg="snippet_stdin",
        )
    )

    insert_after_parser = subparsers.add_parser(
        "insert-after-symbol",
        help="Insert a sibling block after one anchor symbol when the anchor hash still matches.",
    )
    insert_after_parser.add_argument("file_path")
    insert_after_parser.add_argument("--symbol", required=True)
    insert_after_parser.add_argument("--expect-hash", required=True)
    insert_after_group = insert_after_parser.add_mutually_exclusive_group(required=True)
    insert_after_group.add_argument("--snippet-env")
    insert_after_group.add_argument("--snippet-file")
    insert_after_group.add_argument("--snippet-text")
    insert_after_group.add_argument("--snippet-stdin", action="store_true")
    insert_after_parser.add_argument("--check-only", action="store_true")
    insert_after_parser.add_argument("--json", action="store_true")
    insert_after_parser.set_defaults(
        handler=lambda args: _apply_symbol_edit_command(
            args,
            insert_after_symbol,
            render_edit_result,
            render_edit_result_json,
            env_arg="snippet_env",
            file_arg="snippet_file",
            text_arg="snippet_text",
            stdin_arg="snippet_stdin",
        )
    )

    batch_parser = subparsers.add_parser(
        "batch",
        help="Apply a JSON plan of guarded edit commands sequentially.",
    )
    batch_group = batch_parser.add_mutually_exclusive_group(required=True)
    batch_group.add_argument("--plan-env")
    batch_group.add_argument("--plan-file")
    batch_group.add_argument("--plan-text")
    batch_group.add_argument("--plan-stdin", action="store_true")
    batch_parser.add_argument("--check-only", action="store_true")
    batch_parser.add_argument("--json", action="store_true")
    batch_parser.set_defaults(
        handler=lambda args: _apply_batch_edit_command(
            args,
            apply_batch_edits,
            render_batch_edit_result,
            render_batch_edit_result_json,
        )
    )

    imports_parser = subparsers.add_parser(
        "imports-add",
        help="Insert one import statement into the module import block unless it already exists.",
    )
    imports_parser.add_argument("file_path")
    imports_parser.add_argument("--import", dest="import_statement", required=True)
    imports_parser.add_argument("--check-only", action="store_true")
    imports_parser.add_argument("--json", action="store_true")
    imports_parser.set_defaults(
        handler=lambda args: _imports_add(args, add_import_statement, render_edit_result, render_edit_result_json)
    )

    parse_parser = subparsers.add_parser("parse-check", help="Parse one Python file and report syntax validity.")
    parse_parser.add_argument("file_path")
    parse_parser.add_argument("--json", action="store_true")
    parse_parser.set_defaults(
        handler=lambda args: _render_parse_check(
            args,
            parse_check,
            render_parse_check,
            render_parse_check_json,
        )
    )

    args = parser.parse_args(effective_argv)
    if not hasattr(args, "handler"):
        parser.print_help()
        return 0
    try:
        return int(args.handler(args) or 0)
    except CodeMapEditError as error:
        if getattr(args, "json", False):
            print(render_error_json(error, PROJECT_ROOT))
        else:
            print(str(error), file=sys.stderr)
        return 1
    except ValueError as error:
        if getattr(args, "json", False):
            print(json.dumps({"code": "value-error", "message": str(error)}, indent=2, sort_keys=True))
        else:
            print(str(error), file=sys.stderr)
        return 1


def _print_help(text: str) -> int:
    print(text)
    return 0


def _resolve_target(path_text: str) -> Path:
    target = Path(path_text)
    if not target.is_absolute():
        target = (PROJECT_ROOT / target).resolve()
    return target


def _render_code_map(args: argparse.Namespace, render_code_map: object, render_code_map_json: object) -> int:
    target = _resolve_target(args.file_path)
    if args.json:
        print(render_code_map_json(target, PROJECT_ROOT))
        return 0
    print(render_code_map(target, PROJECT_ROOT))
    return 0


def _render_class_diagram(args: argparse.Namespace, render_class_diagram: object) -> int:
    target = _resolve_target(args.target_path)
    output = render_class_diagram(target, PROJECT_ROOT)
    if args.output:
        output_path = _resolve_target(args.output)
        output_path.write_text(output, encoding="utf-8")
        print(output_path)
        return 0
    print(output, end="")
    return 0


def _render_facade_audit(
    args: argparse.Namespace,
    build_facade_audit: object,
    render_facade_audit: object,
    render_facade_audit_json: object,
) -> int:
    target = _resolve_target(args.file_path)
    caller_roots = tuple(_resolve_target(path_text) for path_text in args.callers)
    report = build_facade_audit(
        target,
        args.symbol,
        caller_roots,
        PROJECT_ROOT,
        include_private=args.include_private,
    )
    if args.json:
        print(render_facade_audit_json(report, PROJECT_ROOT))
        return 0
    print(render_facade_audit(report, PROJECT_ROOT))
    return 0


def _render_protocol_audit(
    args: argparse.Namespace,
    build_protocol_audit: object,
    render_protocol_audit: object,
    render_protocol_audit_json: object,
) -> int:
    target = _resolve_target(args.target_path)
    facade_file_path = None if args.facade_file is None else _resolve_target(args.facade_file)
    report = build_protocol_audit(
        target,
        PROJECT_ROOT,
        symbol=args.symbol,
        include_private=args.include_private,
        facade_file_path=facade_file_path,
        facade_symbol=args.facade_symbol,
    )
    if args.json:
        print(render_protocol_audit_json(report, PROJECT_ROOT))
        return 0
    print(render_protocol_audit(report, PROJECT_ROOT))
    return 0


def _render_symbol_snapshot(
    args: argparse.Namespace,
    render_symbol_snapshot: object,
    render_symbol_snapshot_json: object,
) -> int:
    target = _resolve_target(args.file_path)
    if args.json:
        print(render_symbol_snapshot_json(target, PROJECT_ROOT, args.symbol))
        return 0
    print(render_symbol_snapshot(target, PROJECT_ROOT, args.symbol))
    return 0


def _apply_symbol_edit_command(
    args: argparse.Namespace,
    edit_function: object,
    render_edit_result: object,
    render_edit_result_json: object,
    *,
    env_arg: str,
    file_arg: str,
    text_arg: str,
    stdin_arg: str,
) -> int:
    target = _resolve_target(args.file_path)
    replacement_text = _resolve_inline_or_file_text(
        args,
        env_arg=env_arg,
        file_arg=file_arg,
        text_arg=text_arg,
        stdin_arg=stdin_arg,
    )
    result = edit_function(
        target,
        PROJECT_ROOT,
        args.symbol,
        args.expect_hash,
        replacement_text,
        check_only=args.check_only,
    )
    if args.json:
        print(render_edit_result_json(result, PROJECT_ROOT))
        return 0
    print(render_edit_result(result, PROJECT_ROOT))
    return 0


def _resolve_inline_or_file_text(
    args: argparse.Namespace,
    *,
    env_arg: str,
    file_arg: str,
    text_arg: str,
    stdin_arg: str,
) -> str:
    inline_text = getattr(args, text_arg)
    if inline_text is not None:
        return str(inline_text)
    env_name = getattr(args, env_arg)
    if env_name is not None:
        try:
            return os.environ[env_name]
        except KeyError as error:
            raise ValueError(f"environment variable not found: {env_name}") from error
    if getattr(args, stdin_arg):
        return sys.stdin.read()
    file_path_text = getattr(args, file_arg)
    if file_path_text is None:
        raise ValueError(
            "expected one of "
            f"--{env_arg.replace('_', '-')} or "
            f"--{file_arg.replace('_', '-')} or "
            f"--{text_arg.replace('_', '-')} or "
            f"--{stdin_arg.replace('_', '-')}"
        )
    return _resolve_target(file_path_text).read_text(encoding="utf-8")


def _apply_batch_edit_command(
    args: argparse.Namespace,
    apply_batch_edits: object,
    render_batch_edit_result: object,
    render_batch_edit_result_json: object,
) -> int:
    plan = _load_batch_plan(args)
    result = apply_batch_edits(plan, PROJECT_ROOT, check_only=args.check_only)
    if args.json:
        print(render_batch_edit_result_json(result, PROJECT_ROOT))
        return 0
    print(render_batch_edit_result(result, PROJECT_ROOT))
    return 0


def _load_batch_plan(args: argparse.Namespace) -> object:
    if args.plan_text is not None:
        return json.loads(args.plan_text)
    if args.plan_env is not None:
        try:
            return json.loads(os.environ[args.plan_env])
        except KeyError as error:
            raise ValueError(f"environment variable not found: {args.plan_env}") from error
    if args.plan_stdin:
        return json.loads(sys.stdin.read())
    if args.plan_file is not None:
        return json.loads(_resolve_target(args.plan_file).read_text(encoding="utf-8"))
    raise ValueError("expected one of --plan-env or --plan-file or --plan-text or --plan-stdin")


def _render_parse_check(
    args: argparse.Namespace,
    parse_check: object,
    render_parse_check: object,
    render_parse_check_json: object,
) -> int:
    target = _resolve_target(args.file_path)
    result = parse_check(target)
    output = render_parse_check_json(result, PROJECT_ROOT) if args.json else render_parse_check(result, PROJECT_ROOT)
    print(output)
    return 0 if result.ok else 1


def _imports_add(
    args: argparse.Namespace,
    add_import_statement: object,
    render_edit_result: object,
    render_edit_result_json: object,
) -> int:
    target = _resolve_target(args.file_path)
    result = add_import_statement(
        target,
        args.import_statement,
        check_only=args.check_only,
    )
    if args.json:
        print(render_edit_result_json(result, PROJECT_ROOT))
        return 0
    print(render_edit_result(result, PROJECT_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

