import argparse
import json
import os
from pathlib import Path
import sys

from .core import CppCodeMapError
from .core import add_include_statement
from .core import apply_batch_edits
from .core import compact_help
from .core import insert_after_symbol
from .core import insert_before_symbol
from .core import render_batch_edit_result
from .core import render_code_map
from .core import render_edit_result
from .core import render_parse_check
from .core import render_puml_audit
from .core import render_symbol_snapshot
from .core import replace_symbol
from .core import replace_symbol_body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Print and edit C++ AST maps using libclang.")
    subparsers = parser.add_subparsers(dest="command")

    map_parser = subparsers.add_parser("map", help="Print a C++ file symbol map.")
    _add_cpp_context_args(map_parser)
    map_parser.add_argument("--json", action="store_true")

    symbol_parser = subparsers.add_parser("symbol-get", help="Print a C++ symbol snapshot.")
    _add_cpp_context_args(symbol_parser)
    symbol_parser.add_argument("--symbol", required=True)
    symbol_parser.add_argument("--json", action="store_true")

    parse_parser = subparsers.add_parser("parse-check", help="Parse a C++ file and report diagnostics.")
    _add_cpp_context_args(parse_parser)
    parse_parser.add_argument("--json", action="store_true")

    puml_parser = subparsers.add_parser("puml-audit", help="Audit DMA_Plantuml macros against the C++ AST.")
    _add_cpp_context_args(puml_parser)
    puml_parser.add_argument("--json", action="store_true")

    replace_parser = subparsers.add_parser("replace-symbol", help="Replace one symbol with hash guard.")
    _add_edit_args(replace_parser, "replacement")

    replace_body_parser = subparsers.add_parser("replace-symbol-body", help="Replace one symbol body with hash guard.")
    _add_edit_args(replace_body_parser, "replacement")

    insert_before_parser = subparsers.add_parser("insert-before-symbol", help="Insert code before an anchor symbol.")
    _add_edit_args(insert_before_parser, "snippet")

    insert_after_parser = subparsers.add_parser("insert-after-symbol", help="Insert code after an anchor symbol.")
    _add_edit_args(insert_after_parser, "snippet")

    includes_parser = subparsers.add_parser("includes-add", help="Insert one #include statement if missing.")
    includes_parser.add_argument("cpp_file")
    includes_parser.add_argument("--include", dest="include_statement", required=True)
    includes_parser.add_argument("--check-only", action="store_true")
    includes_parser.add_argument("--json", action="store_true")

    batch_parser = subparsers.add_parser("batch", help="Apply a JSON plan of guarded edit commands.")
    batch_group = batch_parser.add_mutually_exclusive_group(required=True)
    batch_group.add_argument("--plan-env")
    batch_group.add_argument("--plan-file")
    batch_group.add_argument("--plan-text")
    batch_group.add_argument("--plan-stdin", action="store_true")
    batch_parser.add_argument("--compile-db", "-p")
    batch_parser.add_argument("--clang-arg", action="append", default=[])
    batch_parser.add_argument("--check-only", action="store_true")
    batch_parser.add_argument("--json", action="store_true")

    subparsers.add_parser("help", help="Print compact help.")

    args = parser.parse_args(argv)
    if args.command in (None, "help"):
        print(compact_help())
        return 0

    try:
        return _dispatch(args, parser)
    except CppCodeMapError as exc:
        if getattr(args, "json", False):
            print(exc.to_json())
        else:
            print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        if getattr(args, "json", False):
            print(json.dumps({"error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(str(exc), file=sys.stderr)
        return 1


def _add_cpp_context_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("cpp_file")
    parser.add_argument("--compile-db", "-p")
    parser.add_argument("--clang-arg", action="append", default=[])


def _add_edit_args(parser: argparse.ArgumentParser, text_kind: str) -> None:
    _add_cpp_context_args(parser)
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--expect-hash", required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(f"--{text_kind}-env")
    group.add_argument(f"--{text_kind}-file")
    group.add_argument(f"--{text_kind}-text")
    group.add_argument(f"--{text_kind}-stdin", action="store_true")
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--json", action="store_true")


def _dispatch(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "batch":
        compile_db = _compile_db(args)
        result = apply_batch_edits(_load_batch_plan(args),
                                   compile_db,
                                   clang_args=tuple(args.clang_arg),
                                   check_only=args.check_only)
        print(render_batch_edit_result(result, json_output=args.json))
        return 0
    target = Path(args.cpp_file).resolve()
    compile_db = _compile_db(args)
    clang_args = tuple(getattr(args, "clang_arg", ()))
    if args.command == "map":
        print(render_code_map(target, compile_db, clang_args=clang_args, json_output=args.json))
    elif args.command == "symbol-get":
        print(render_symbol_snapshot(target,
                                     args.symbol,
                                     compile_db,
                                     clang_args=clang_args,
                                     json_output=args.json))
    elif args.command == "parse-check":
        print(render_parse_check(target, compile_db, clang_args=clang_args, json_output=args.json))
    elif args.command == "puml-audit":
        print(render_puml_audit(target, compile_db, clang_args=clang_args, json_output=args.json))
    elif args.command == "replace-symbol":
        result = replace_symbol(target,
                                args.symbol,
                                args.expect_hash,
                                _resolve_text(args, "replacement"),
                                compile_db,
                                clang_args=clang_args,
                                check_only=args.check_only)
        print(render_edit_result(result, json_output=args.json))
    elif args.command == "replace-symbol-body":
        result = replace_symbol_body(target,
                                     args.symbol,
                                     args.expect_hash,
                                     _resolve_text(args, "replacement"),
                                     compile_db,
                                     clang_args=clang_args,
                                     check_only=args.check_only)
        print(render_edit_result(result, json_output=args.json))
    elif args.command == "insert-before-symbol":
        result = insert_before_symbol(target,
                                      args.symbol,
                                      args.expect_hash,
                                      _resolve_text(args, "snippet"),
                                      compile_db,
                                      clang_args=clang_args,
                                      check_only=args.check_only)
        print(render_edit_result(result, json_output=args.json))
    elif args.command == "insert-after-symbol":
        result = insert_after_symbol(target,
                                     args.symbol,
                                     args.expect_hash,
                                     _resolve_text(args, "snippet"),
                                     compile_db,
                                     clang_args=clang_args,
                                     check_only=args.check_only)
        print(render_edit_result(result, json_output=args.json))
    elif args.command == "includes-add":
        result = add_include_statement(target,
                                       args.include_statement,
                                       check_only=args.check_only)
        print(render_edit_result(result, json_output=args.json))
    else:
        parser.error(f"unknown command {args.command!r}")
    return 0


def _compile_db(args: argparse.Namespace) -> Path | None:
    return Path(args.compile_db).resolve() if getattr(args, "compile_db", None) else None


def _resolve_text(args: argparse.Namespace, prefix: str) -> str:
    text = getattr(args, f"{prefix}_text")
    if text is not None:
        return str(text)
    env_name = getattr(args, f"{prefix}_env")
    if env_name is not None:
        try:
            return os.environ[env_name]
        except KeyError as exc:
            raise ValueError(f"environment variable not found: {env_name}") from exc
    if getattr(args, f"{prefix}_stdin"):
        return sys.stdin.read()
    file_name = getattr(args, f"{prefix}_file")
    if file_name is None:
        raise ValueError(f"expected {prefix} text source")
    return Path(file_name).resolve().read_text(encoding="utf-8")


def _load_batch_plan(args: argparse.Namespace) -> object:
    if args.plan_text is not None:
        return json.loads(args.plan_text)
    if args.plan_env is not None:
        try:
            return json.loads(os.environ[args.plan_env])
        except KeyError as exc:
            raise ValueError(f"environment variable not found: {args.plan_env}") from exc
    if args.plan_stdin:
        return json.loads(sys.stdin.read())
    if args.plan_file is not None:
        return json.loads(Path(args.plan_file).resolve().read_text(encoding="utf-8"))
    raise ValueError("expected batch plan source")
