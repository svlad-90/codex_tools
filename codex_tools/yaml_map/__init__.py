from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))


def main(argv: list[str] | None = None) -> int:
    from .core import (
        YamlMapEditError,
        compact_help,
        insert_item,
        parse_check,
        path_delete,
        path_get,
        path_set,
        project_map,
        render_edit_result,
        render_edit_result_json,
        render_error_json,
        render_parse_check,
        render_parse_check_json,
        render_path_snapshot,
        render_path_snapshot_json,
        render_project_map,
        render_project_map_json,
        render_yaml_map,
        render_yaml_map_json,
    )

    effective_argv = list(sys.argv[1:] if argv is None else argv)
    known_commands = {
        "help",
        "map",
        "project-map",
        "path-get",
        "path-set",
        "item-insert",
        "path-delete",
        "parse-check",
    }
    if effective_argv and effective_argv[0] not in known_commands and not effective_argv[0].startswith("-"):
        effective_argv = ["map", *effective_argv]

    parser = argparse.ArgumentParser(description="Inspect YAML structure and apply guarded path-level edits.")
    subparsers = parser.add_subparsers(dest="command")

    help_parser = subparsers.add_parser("help", help="Print compact CLI synopsis.")
    help_parser.set_defaults(handler=lambda _args: _print_help(compact_help()))

    map_parser = subparsers.add_parser("map", help="Print a compact merged structure map for one YAML file.")
    map_parser.add_argument("file_path")
    map_parser.add_argument("--json", action="store_true")
    map_parser.set_defaults(handler=lambda args: _render_map(args, render_yaml_map, render_yaml_map_json))

    project_parser = subparsers.add_parser("project-map", help="List YAML files under a path with compact summaries.")
    project_parser.add_argument("target_path", nargs="?", default=".")
    project_parser.add_argument("--deep", action="store_true")
    project_parser.add_argument("--json", action="store_true")
    project_parser.set_defaults(
        handler=lambda args: _render_project_map(
            args,
            project_map,
            render_project_map,
            render_project_map_json,
        )
    )

    get_parser = subparsers.add_parser("path-get", help="Resolve one YAML path and print its hash and value.")
    get_parser.add_argument("file_path")
    get_parser.add_argument("--path", required=True)
    get_parser.add_argument("--json", action="store_true")
    get_parser.set_defaults(
        handler=lambda args: _render_path_get(
            args,
            path_get,
            render_path_snapshot,
            render_path_snapshot_json,
        )
    )

    set_parser = subparsers.add_parser(
        "path-set",
        help="Replace one YAML path when the expected subtree hash still matches.",
    )
    set_parser.add_argument("file_path")
    set_parser.add_argument("--path", required=True)
    set_parser.add_argument("--expect-hash", required=True)
    set_group = set_parser.add_mutually_exclusive_group(required=True)
    set_group.add_argument("--value-json")
    set_group.add_argument("--value-file")
    set_group.add_argument("--value-stdin", action="store_true")
    set_parser.add_argument("--check-only", action="store_true")
    set_parser.add_argument("--json", action="store_true")
    set_parser.set_defaults(handler=lambda args: _apply_path_set(args, path_set, render_edit_result, render_edit_result_json))

    insert_parser = subparsers.add_parser(
        "item-insert",
        help="Insert one mapping entry or list item into a YAML container when the expected hash still matches.",
    )
    insert_parser.add_argument("file_path")
    insert_parser.add_argument("--path", required=True)
    insert_parser.add_argument("--expect-hash", required=True)
    insert_parser.add_argument("--key")
    insert_parser.add_argument("--index", type=int)
    insert_group = insert_parser.add_mutually_exclusive_group(required=True)
    insert_group.add_argument("--value-json")
    insert_group.add_argument("--value-file")
    insert_group.add_argument("--value-stdin", action="store_true")
    insert_parser.add_argument("--check-only", action="store_true")
    insert_parser.add_argument("--json", action="store_true")
    insert_parser.set_defaults(
        handler=lambda args: _apply_insert(args, insert_item, render_edit_result, render_edit_result_json)
    )

    delete_parser = subparsers.add_parser(
        "path-delete",
        help="Delete one YAML path when the expected subtree hash still matches.",
    )
    delete_parser.add_argument("file_path")
    delete_parser.add_argument("--path", required=True)
    delete_parser.add_argument("--expect-hash", required=True)
    delete_parser.add_argument("--check-only", action="store_true")
    delete_parser.add_argument("--json", action="store_true")
    delete_parser.set_defaults(
        handler=lambda args: _apply_delete(args, path_delete, render_edit_result, render_edit_result_json)
    )

    parse_parser = subparsers.add_parser("parse-check", help="Parse one YAML file and report validity.")
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
    except YamlMapEditError as error:
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


def _render_map(args: argparse.Namespace, render_yaml_map: object, render_yaml_map_json: object) -> int:
    target = _resolve_target(args.file_path)
    print(render_yaml_map_json(target, PROJECT_ROOT) if args.json else render_yaml_map(target, PROJECT_ROOT))
    return 0


def _render_project_map(
    args: argparse.Namespace,
    project_map: object,
    render_project_map: object,
    render_project_map_json: object,
) -> int:
    target = _resolve_target(args.target_path)
    report = project_map(target, PROJECT_ROOT, deep=args.deep)
    print(render_project_map_json(report, PROJECT_ROOT) if args.json else render_project_map(report, PROJECT_ROOT))
    return 0


def _render_path_get(
    args: argparse.Namespace,
    path_get: object,
    render_path_snapshot: object,
    render_path_snapshot_json: object,
) -> int:
    target = _resolve_target(args.file_path)
    snapshot = path_get(target, args.path)
    print(render_path_snapshot_json(snapshot, PROJECT_ROOT) if args.json else render_path_snapshot(snapshot, PROJECT_ROOT))
    return 0


def _apply_path_set(
    args: argparse.Namespace,
    path_set: object,
    render_edit_result: object,
    render_edit_result_json: object,
) -> int:
    target = _resolve_target(args.file_path)
    result = path_set(
        target,
        args.path,
        args.expect_hash,
        _load_value_payload(args),
        check_only=args.check_only,
    )
    print(render_edit_result_json(result, PROJECT_ROOT) if args.json else render_edit_result(result, PROJECT_ROOT))
    return 0


def _apply_insert(
    args: argparse.Namespace,
    insert_item: object,
    render_edit_result: object,
    render_edit_result_json: object,
) -> int:
    target = _resolve_target(args.file_path)
    result = insert_item(
        target,
        args.path,
        args.expect_hash,
        _load_value_payload(args),
        key=args.key,
        index=args.index,
        check_only=args.check_only,
    )
    print(render_edit_result_json(result, PROJECT_ROOT) if args.json else render_edit_result(result, PROJECT_ROOT))
    return 0


def _apply_delete(
    args: argparse.Namespace,
    path_delete: object,
    render_edit_result: object,
    render_edit_result_json: object,
) -> int:
    target = _resolve_target(args.file_path)
    result = path_delete(
        target,
        args.path,
        args.expect_hash,
        check_only=args.check_only,
    )
    print(render_edit_result_json(result, PROJECT_ROOT) if args.json else render_edit_result(result, PROJECT_ROOT))
    return 0


def _load_value_payload(args: argparse.Namespace) -> object:
    if args.value_json is not None:
        return json.loads(args.value_json)
    if args.value_file is not None:
        return json.loads(_resolve_target(args.value_file).read_text(encoding="utf-8"))
    if getattr(args, "value_stdin", False):
        return json.loads(sys.stdin.read())
    raise ValueError("expected one of --value-json, --value-file, or --value-stdin")


def _render_parse_check(
    args: argparse.Namespace,
    parse_check: object,
    render_parse_check: object,
    render_parse_check_json: object,
) -> int:
    target = _resolve_target(args.file_path)
    result = parse_check(target)
    print(render_parse_check_json(result, PROJECT_ROOT) if args.json else render_parse_check(result, PROJECT_ROOT))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
