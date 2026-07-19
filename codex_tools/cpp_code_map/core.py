from __future__ import annotations

import difflib
from dataclasses import asdict
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
from typing import Any
from uuid import uuid4


SYMBOL_KINDS = {
    "NAMESPACE",
    "CLASS_DECL",
    "STRUCT_DECL",
    "CLASS_TEMPLATE",
    "FUNCTION_DECL",
    "CXX_METHOD",
    "CONSTRUCTOR",
    "DESTRUCTOR",
    "FIELD_DECL",
    "ENUM_DECL",
}


@dataclass(frozen=True)
class SourceSpan:
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class CppSymbol:
    name: str
    qualified_name: str
    kind: str
    span: SourceSpan
    body_span: SourceSpan | None
    hash: str
    body_hash: str | None
    bases: tuple[str, ...] = ()
    children: tuple["CppSymbol", ...] = ()


@dataclass(frozen=True)
class SymbolSnapshot:
    symbol: str
    qualified: str
    kind: str
    span: SourceSpan
    hash: str
    body_span: SourceSpan | None
    body_hash: str | None


@dataclass(frozen=True)
class EditResult:
    file_path: Path
    operation: str
    target: str
    changed: bool
    check_only: bool
    old_hash: str | None = None
    new_hash: str | None = None
    snapshot: SymbolSnapshot | None = None
    insert_line: int | None = None
    statement: str | None = None
    diff: str | None = None


@dataclass(frozen=True)
class BatchEditResult:
    operations: tuple[EditResult, ...]
    check_only: bool


@dataclass(frozen=True)
class ParseCheckResult:
    ok: bool
    diagnostics: tuple[str, ...]


@dataclass(frozen=True)
class PumlDependency:
    target: str
    macro: str
    line: int
    checked: bool
    multiplicity_from: str | None
    multiplicity_to: str | None
    label: str | None


@dataclass(frozen=True)
class PumlClassBlock:
    name: str
    kind: str
    line: int
    package: str | None
    checked: bool
    inheritances: tuple[tuple[str, int, bool], ...]
    dependencies: tuple[PumlDependency, ...]


@dataclass(frozen=True)
class PumlClassRelations:
    bases: tuple[str, ...]
    related_types: tuple[str, ...]


@dataclass(frozen=True)
class PumlAuditFinding:
    severity: str
    line: int
    code: str
    message: str


@dataclass(frozen=True)
class PumlAuditResult:
    file_path: Path
    ok: bool
    classes: tuple[PumlClassBlock, ...]
    findings: tuple[PumlAuditFinding, ...]


class CppCodeMapError(Exception):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_json(self) -> str:
        return json.dumps({"error": self.message, "details": self.details}, indent=2)


def compact_help() -> str:
    return "\n".join([
        "cpp_code_map help",
        "cpp_code_map map <cpp_file> [--compile-db <build-dir-or-json>] "
        "[--clang-arg <arg>] [--json]",
        "cpp_code_map symbol-get <cpp_file> --symbol <qualified-name> "
        "[--compile-db <build-dir-or-json>] [--clang-arg <arg>] [--json]",
        "cpp_code_map parse-check <cpp_file> [--compile-db <build-dir-or-json>] "
        "[--clang-arg <arg>] [--json]",
        "cpp_code_map replace-symbol <cpp_file> --symbol <name> --expect-hash <sha256> "
        "(--replacement-env <VAR> | --replacement-file <path> | --replacement-text <text> | --replacement-stdin) "
        "[--compile-db <build-dir-or-json>] [--clang-arg <arg>] [--check-only] [--json]",
        "cpp_code_map replace-symbol-body <cpp_file> --symbol <name> --expect-hash <sha256> "
        "(--replacement-env <VAR> | --replacement-file <path> | --replacement-text <text> | --replacement-stdin) "
        "[--compile-db <build-dir-or-json>] [--clang-arg <arg>] [--check-only] [--json]",
        "cpp_code_map insert-before-symbol <cpp_file> --symbol <name> --expect-hash <sha256> "
        "(--snippet-env <VAR> | --snippet-file <path> | --snippet-text <text> | --snippet-stdin) "
        "[--compile-db <build-dir-or-json>] [--clang-arg <arg>] [--check-only] [--json]",
        "cpp_code_map insert-after-symbol <cpp_file> --symbol <name> --expect-hash <sha256> "
        "(--snippet-env <VAR> | --snippet-file <path> | --snippet-text <text> | --snippet-stdin) "
        "[--compile-db <build-dir-or-json>] [--clang-arg <arg>] [--check-only] [--json]",
        "cpp_code_map includes-add <cpp_file> --include <statement> [--check-only] [--json]",
        "cpp_code_map batch (--plan-env <VAR> | --plan-file <path> | --plan-text <json> | --plan-stdin) "
        "[--compile-db <build-dir-or-json>] [--clang-arg <arg>] [--check-only] [--json]",
        "cpp_code_map puml-audit <cpp_file> [--compile-db <build-dir-or-json>] [--clang-arg <arg>] [--json]",
    ])


def render_code_map(file_path: Path,
                    compile_db: Path | None,
                    *,
                    clang_args: tuple[str, ...] = (),
                    json_output: bool = False) -> str:
    source, symbols, _ = _parse_symbols(file_path, compile_db, clang_args)
    if json_output:
        return json.dumps({
            "file": str(file_path),
            "symbols": [_symbol_payload(symbol) for symbol in symbols],
        }, indent=2)
    lines = [str(file_path)]
    for symbol in symbols:
        lines.extend(_render_symbol(symbol, 0))
    return "\n".join(lines)


def render_symbol_snapshot(file_path: Path,
                           symbol_name: str,
                           compile_db: Path | None,
                           *,
                           clang_args: tuple[str, ...] = (),
                           json_output: bool = False) -> str:
    source, symbols, _ = _parse_symbols(file_path, compile_db, clang_args)
    del source
    snapshot = _snapshot_for_symbol(_resolve_symbol(symbols, symbol_name, file_path))
    if json_output:
        return json.dumps(_snapshot_payload(snapshot), indent=2)
    return "\n".join([
        f"{file_path} :: symbol-get",
        f"symbol: {snapshot.symbol}",
        f"qualified: {snapshot.qualified}",
        f"kind: {snapshot.kind}",
        f"span: {_span_text(snapshot.span)} hash={snapshot.hash}",
        f"body: {_span_text(snapshot.body_span)} hash={snapshot.body_hash}",
    ])


def render_parse_check(file_path: Path,
                       compile_db: Path | None,
                       *,
                       clang_args: tuple[str, ...] = (),
                       json_output: bool = False) -> str:
    _, _, diagnostics = _parse_symbols(file_path, compile_db, clang_args)
    errors = [diag for diag in diagnostics if " error: " in diag.lower()]
    result = ParseCheckResult(ok=not errors, diagnostics=tuple(diagnostics))
    if json_output:
        return json.dumps(asdict(result), indent=2)
    if result.ok:
        if result.diagnostics:
            return f"{file_path} :: parse-check ok with diagnostics\n" + "\n".join(result.diagnostics)
        return f"{file_path} :: parse-check ok"
    return f"{file_path} :: parse-check error\n" + "\n".join(result.diagnostics)


def render_puml_audit(file_path: Path,
                      compile_db: Path | None,
                      *,
                      clang_args: tuple[str, ...] = (),
                      json_output: bool = False) -> str:
    result = build_puml_audit(file_path, compile_db, clang_args=clang_args)
    if json_output:
        return json.dumps(_puml_audit_payload(result), indent=2, sort_keys=True)
    lines = [
        f"{file_path} :: puml-audit "
        + f"ok={str(result.ok).lower()} "
        + f"classes={len(result.classes)} "
        + f"findings={len(result.findings)}",
    ]
    for finding in result.findings:
        lines.append(f"{finding.severity} {finding.line}: {finding.code}: {finding.message}")
    return "\n".join(lines)


def build_puml_audit(file_path: Path,
                     compile_db: Path | None,
                     *,
                     clang_args: tuple[str, ...] = ()) -> PumlAuditResult:
    source = _read_source(file_path)
    compile_args = _compile_args(file_path, compile_db, clang_args)
    classes = _parse_puml_blocks(source, defined_macros=_defined_macros(compile_args))
    target_class_names = tuple(class_block.name for class_block in classes)
    source, _, diagnostics, class_relations = _parse_puml_context(file_path,
                                                                 compile_db,
                                                                 clang_args,
                                                                 target_class_names)
    findings: list[PumlAuditFinding] = []
    for class_block in classes:
        ast_relations = _find_class_relations(class_relations, class_block.name)
        if class_block.checked and ast_relations is None:
            findings.append(PumlAuditFinding(severity="error",
                                             line=class_block.line,
                                             code="missing-class",
                                             message=f"PUML class {class_block.name} was not found in AST"))
            continue
        if ast_relations is None:
            continue
        base_names = {_short_type_name(base) for base in ast_relations.bases}
        for base_name, line, checked in class_block.inheritances:
            expected = _short_type_name(base_name)
            if expected not in base_names:
                severity = "error" if checked else "warning"
                findings.append(PumlAuditFinding(
                    severity=severity,
                    line=line,
                    code="inheritance-mismatch",
                    message=(
                        f"PUML inheritance {class_block.name} -> {base_name} "
                        + f"not found in AST bases {sorted(base_names)}"
                    ),
                ))
        for dependency in class_block.dependencies:
            if not dependency.checked:
                continue
            if not _has_related_type(ast_relations.related_types, dependency.target):
                findings.append(PumlAuditFinding(
                    severity="error",
                    line=dependency.line,
                    code="dependency-mismatch",
                    message=(
                        f"PUML dependency {class_block.name} -> {dependency.target} "
                        + "not found in AST related types "
                        + _related_types_summary(ast_relations.related_types)
                    ),
                ))
    for diagnostic in diagnostics:
        if " error: " in diagnostic.lower():
            findings.append(PumlAuditFinding(severity="error",
                                             line=0,
                                             code="parse-error",
                                             message=diagnostic))
    return PumlAuditResult(file_path=file_path,
                           ok=not any(finding.severity == "error" for finding in findings),
                           classes=classes,
                           findings=tuple(findings))


def replace_symbol(file_path: Path,
                   symbol_name: str,
                   expected_hash: str,
                   replacement_text: str,
                   compile_db: Path | None,
                   *,
                   clang_args: tuple[str, ...] = (),
                   check_only: bool = False) -> EditResult:
    return _apply_symbol_edit(file_path,
                              symbol_name,
                              expected_hash,
                              replacement_text,
                              compile_db,
                              clang_args=clang_args,
                              operation="replace-symbol",
                              scope="node",
                              check_only=check_only)


def replace_symbol_body(file_path: Path,
                        symbol_name: str,
                        expected_hash: str,
                        replacement_text: str,
                        compile_db: Path | None,
                        *,
                        clang_args: tuple[str, ...] = (),
                        check_only: bool = False) -> EditResult:
    return _apply_symbol_edit(file_path,
                              symbol_name,
                              expected_hash,
                              replacement_text,
                              compile_db,
                              clang_args=clang_args,
                              operation="replace-symbol-body",
                              scope="body",
                              check_only=check_only)


def insert_before_symbol(file_path: Path,
                         symbol_name: str,
                         expected_hash: str,
                         snippet_text: str,
                         compile_db: Path | None,
                         *,
                         clang_args: tuple[str, ...] = (),
                         check_only: bool = False) -> EditResult:
    return _insert_relative_to_symbol(file_path,
                                      symbol_name,
                                      expected_hash,
                                      snippet_text,
                                      compile_db,
                                      clang_args=clang_args,
                                      position="before",
                                      check_only=check_only)


def insert_after_symbol(file_path: Path,
                        symbol_name: str,
                        expected_hash: str,
                        snippet_text: str,
                        compile_db: Path | None,
                        *,
                        clang_args: tuple[str, ...] = (),
                        check_only: bool = False) -> EditResult:
    return _insert_relative_to_symbol(file_path,
                                      symbol_name,
                                      expected_hash,
                                      snippet_text,
                                      compile_db,
                                      clang_args=clang_args,
                                      position="after",
                                      check_only=check_only)


def add_include_statement(file_path: Path,
                          statement: str,
                          *,
                          check_only: bool = False) -> EditResult:
    source, encoding = _read_source_with_encoding(file_path)
    result, new_source = _add_include_to_source(file_path,
                                                source,
                                                statement,
                                                check_only=check_only)
    if not check_only:
        _atomic_write_text(file_path, new_source, encoding)
    return result


def apply_batch_edits(plan: object,
                      compile_db: Path | None,
                      *,
                      clang_args: tuple[str, ...] = (),
                      check_only: bool = False) -> BatchEditResult:
    payload = _normalized_batch_plan(plan)
    effective_check_only = check_only or bool(payload["check_only"])
    staged_sources: dict[Path, tuple[str, str]] = {}
    results: list[EditResult] = []
    for index, operation in enumerate(payload["operations"]):
        result, new_source, encoding = _apply_batch_operation(operation,
                                                              staged_sources,
                                                              compile_db,
                                                              clang_args=clang_args,
                                                              check_only=effective_check_only,
                                                              operation_index=index)
        file_path = _batch_file_path(operation, operation_index=index)
        staged_sources[file_path] = (new_source, encoding)
        results.append(result)
    if not effective_check_only:
        for file_path, (source, encoding) in staged_sources.items():
            if any(result.changed and result.file_path == file_path for result in results):
                _atomic_write_text(file_path, source, encoding)
    return BatchEditResult(operations=tuple(results), check_only=effective_check_only)


def render_edit_result(result: EditResult, *, json_output: bool = False) -> str:
    if json_output:
        return json.dumps(_edit_result_payload(result), indent=2, sort_keys=True)
    parts = [
        f"target={result.target}",
        f"changed={str(result.changed).lower()}",
        f"check_only={str(result.check_only).lower()}",
    ]
    if result.old_hash is not None:
        parts.append(f"old_hash={result.old_hash}")
    if result.new_hash is not None:
        parts.append(f"new_hash={result.new_hash}")
    if result.insert_line is not None:
        parts.append(f"insert_line={result.insert_line}")
    rendered = f"{result.file_path} :: {result.operation} " + " ".join(parts)
    if result.diff:
        return rendered + "\n" + result.diff
    return rendered


def render_batch_edit_result(result: BatchEditResult, *, json_output: bool = False) -> str:
    if json_output:
        return json.dumps({
            "check_only": result.check_only,
            "operations": [_edit_result_payload(operation) for operation in result.operations],
        }, indent=2, sort_keys=True)
    changed_count = sum(1 for operation in result.operations if operation.changed)
    lines = [
        "cpp_code_map :: batch "
        + f"operations={len(result.operations)} "
        + f"changed={changed_count} "
        + f"check_only={str(result.check_only).lower()}",
    ]
    for operation in result.operations:
        lines.append("")
        lines.append(render_edit_result(operation))
    return "\n".join(lines)


def render_code_map_json(file_path: Path,
                         compile_db: Path | None = None,
                         *,
                         clang_args: tuple[str, ...] = ()) -> str:
    return render_code_map(file_path,
                           compile_db,
                           clang_args=clang_args,
                           json_output=True)


def render_symbol_snapshot_json(file_path: Path,
                                symbol_name: str,
                                compile_db: Path | None = None,
                                *,
                                clang_args: tuple[str, ...] = ()) -> str:
    return render_symbol_snapshot(file_path,
                                  symbol_name,
                                  compile_db,
                                  clang_args=clang_args,
                                  json_output=True)


def render_parse_check_json(file_path: Path,
                            compile_db: Path | None = None,
                            *,
                            clang_args: tuple[str, ...] = ()) -> str:
    return render_parse_check(file_path,
                              compile_db,
                              clang_args=clang_args,
                              json_output=True)


def _resolve_symbol(symbols: tuple[CppSymbol, ...], symbol_name: str, file_path: Path) -> CppSymbol:
    matches = [symbol for symbol in _flatten_symbols(symbols)
               if symbol.qualified_name == symbol_name
               or symbol.name == symbol_name
               or _symbol_signature(symbol) == symbol_name]
    if not matches:
        raise CppCodeMapError(f"symbol {symbol_name!r} not found",
                              details={"file": str(file_path), "symbol": symbol_name})
    if len(matches) > 1:
        raise CppCodeMapError(f"symbol {symbol_name!r} is ambiguous",
                              details={"matches": [match.qualified_name for match in matches]})
    return matches[0]


def _snapshot_for_symbol(symbol: CppSymbol) -> SymbolSnapshot:
    return SymbolSnapshot(symbol=symbol.name,
                          qualified=symbol.qualified_name,
                          kind=symbol.kind,
                          span=symbol.span,
                          hash=symbol.hash,
                          body_span=symbol.body_span,
                          body_hash=symbol.body_hash)


def _apply_symbol_edit(file_path: Path,
                       symbol_name: str,
                       expected_hash: str,
                       replacement_text: str,
                       compile_db: Path | None,
                       *,
                       clang_args: tuple[str, ...],
                       operation: str,
                       scope: str,
                       check_only: bool) -> EditResult:
    source, encoding = _read_source_with_encoding(file_path)
    _, symbols, _ = _parse_symbols_from_source(file_path,
                                               source,
                                               compile_db,
                                               clang_args)
    symbol = _resolve_symbol(symbols, symbol_name, file_path)
    snapshot = _snapshot_for_symbol(symbol)
    span = symbol.span if scope == "node" else symbol.body_span
    current_hash = symbol.hash if scope == "node" else symbol.body_hash
    if span is None or current_hash is None:
        raise CppCodeMapError(f"symbol has no replaceable {scope}: {symbol.qualified_name}",
                              details={"file": str(file_path), "symbol": symbol.qualified_name})
    if current_hash != expected_hash:
        raise CppCodeMapError(
            f"symbol {scope} hash mismatch: expected={expected_hash} actual={current_hash}",
            details={"file": str(file_path),
                     "symbol": symbol.qualified_name,
                     "expected_hash": expected_hash,
                     "actual_hash": current_hash,
                     "snapshot": _snapshot_payload(snapshot)},
        )
    new_source = source[:span.start_offset] + _normalize_block(replacement_text) + source[span.end_offset:]
    _validate_cpp_source(file_path,
                         new_source,
                         compile_db,
                         clang_args,
                         symbol=symbol.qualified_name)
    _, new_symbols, _ = _parse_symbols_from_source(file_path,
                                                   new_source,
                                                   compile_db,
                                                   clang_args)
    new_symbol = _resolve_symbol(new_symbols, symbol_name, file_path)
    new_snapshot = _snapshot_for_symbol(new_symbol)
    new_hash = new_symbol.hash if scope == "node" else new_symbol.body_hash
    result = EditResult(file_path=file_path,
                        operation=operation,
                        target=new_symbol.qualified_name,
                        changed=source != new_source,
                        check_only=check_only,
                        old_hash=current_hash,
                        new_hash=new_hash,
                        snapshot=new_snapshot,
                        diff=_render_unified_diff(source, new_source, file_path))
    if not check_only:
        _atomic_write_text(file_path, new_source, encoding)
    return result


def _insert_relative_to_symbol(file_path: Path,
                               symbol_name: str,
                               expected_hash: str,
                               snippet_text: str,
                               compile_db: Path | None,
                               *,
                               clang_args: tuple[str, ...],
                               position: str,
                               check_only: bool) -> EditResult:
    source, encoding = _read_source_with_encoding(file_path)
    _, symbols, _ = _parse_symbols_from_source(file_path,
                                               source,
                                               compile_db,
                                               clang_args)
    symbol = _resolve_symbol(symbols, symbol_name, file_path)
    snapshot = _snapshot_for_symbol(symbol)
    if symbol.hash != expected_hash:
        raise CppCodeMapError(
            f"anchor symbol hash mismatch: expected={expected_hash} actual={symbol.hash}",
            details={"file": str(file_path),
                     "symbol": symbol.qualified_name,
                     "expected_hash": expected_hash,
                     "actual_hash": symbol.hash,
                     "snapshot": _snapshot_payload(snapshot)},
        )
    line_offsets = _line_start_offsets(source)
    if position == "before":
        insert_offset = line_offsets[symbol.span.start_line - 1]
        insert_line = symbol.span.start_line
    else:
        insert_offset = symbol.span.end_offset
        if source[insert_offset:insert_offset + 1] == "\n":
            insert_offset += 1
        insert_line = symbol.span.end_line + 1
    new_source = source[:insert_offset] + _normalize_block(snippet_text) + source[insert_offset:]
    _validate_cpp_source(file_path,
                         new_source,
                         compile_db,
                         clang_args,
                         symbol=symbol.qualified_name)
    result = EditResult(file_path=file_path,
                        operation=f"insert-{position}-symbol",
                        target=symbol.qualified_name,
                        changed=source != new_source,
                        check_only=check_only,
                        old_hash=symbol.hash,
                        new_hash=symbol.hash,
                        snapshot=snapshot,
                        insert_line=insert_line,
                        diff=_render_unified_diff(source, new_source, file_path))
    if not check_only:
        _atomic_write_text(file_path, new_source, encoding)
    return result


def _parse_symbols_from_source(file_path: Path,
                               source: str,
                               compile_db: Path | None,
                               extra_args: tuple[str, ...]) -> tuple[str, tuple[CppSymbol, ...], tuple[str, ...]]:
    temp_path = file_path.with_name(f"{file_path.name}.{uuid4().hex}.tmp{file_path.suffix}")
    temp_path.write_text(source, encoding="utf-8")
    try:
        return _parse_symbols(temp_path, compile_db, extra_args, original_file=file_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _parse_puml_context(file_path: Path,
                        compile_db: Path | None,
                        extra_args: tuple[str, ...],
                        target_class_names: tuple[str, ...]) -> tuple[
                            str,
                            tuple[CppSymbol, ...],
                            tuple[str, ...],
                            dict[str, PumlClassRelations],
                        ]:
    clang = _load_clang()
    source = _read_source(file_path)
    args = _compile_args(file_path, compile_db, extra_args)
    index = clang.Index.create()
    try:
        translation_unit = index.parse(str(file_path),
                                       args=args,
                                       options=clang.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
    except Exception as exc:  # pragma: no cover - depends on local libclang.
        raise CppCodeMapError(f"failed to parse {file_path}: {exc}",
                              details={"file": str(file_path), "args": args}) from exc
    diagnostics = tuple(str(diagnostic) for diagnostic in translation_unit.diagnostics)
    symbols = tuple(_collect_symbols(translation_unit.cursor, file_path, source, ()))
    class_relations = _collect_translation_unit_class_relations(translation_unit.cursor,
                                                               file_path,
                                                               target_class_names)
    return source, symbols, diagnostics, class_relations


def _parse_puml_blocks(source: str, *, defined_macros: frozenset[str] = frozenset()) -> tuple[PumlClassBlock, ...]:
    package: str | None = None
    current: dict[str, Any] | None = None
    classes: list[PumlClassBlock] = []
    active_stack: list[tuple[bool, bool, bool]] = []
    for line_number, line in enumerate(source.splitlines(), start=1):
        directive = _preprocessor_directive(line)
        if directive is not None:
            _update_active_stack(active_stack, directive, defined_macros)
            continue
        if not _is_preprocessor_active(active_stack):
            continue
        macro = _parse_macro_call(line)
        if macro is None:
            continue
        name, args = macro
        if name == "PUML_PACKAGE_BEGIN" and args:
            package = args[0]
            continue
        if name == "PUML_PACKAGE_END":
            package = None
            continue
        if name in {
            "PUML_CLASS_BEGIN",
            "PUML_CLASS_BEGIN_CHECKED",
            "PUML_ABSTRACT_CLASS_BEGIN",
            "PUML_ABSTRACT_CLASS_BEGIN_CHECKED",
            "PUML_INTERFACE_BEGIN",
            "PUML_INTERFACE_BEGIN_CHECKED",
            "PUML_SINGLETONE_BEGIN",
            "PUML_SINGLETONE_BEGIN_CHECKED",
        } and args:
            current = {
                "name": args[0],
                "kind": name,
                "line": line_number,
                "package": package,
                "checked": name.endswith("_CHECKED"),
                "inheritances": [],
                "dependencies": [],
            }
            continue
        if name in {
            "PUML_CLASS_END",
            "PUML_ABSTRACT_CLASS_END",
            "PUML_INTERFACE_END",
            "PUML_SINGLETONE_END",
        }:
            if current is not None:
                classes.append(PumlClassBlock(
                    name=current["name"],
                    kind=current["kind"],
                    line=current["line"],
                    package=current["package"],
                    checked=current["checked"],
                    inheritances=tuple(current["inheritances"]),
                    dependencies=tuple(current["dependencies"]),
                ))
                current = None
            continue
        if current is not None and name in {"PUML_INHERITANCE", "PUML_INHERITANCE_CHECKED"} and args:
            current["inheritances"].append((args[0], line_number, name.endswith("_CHECKED")))
            continue
        if current is not None and name in {
            "PUML_COMPOSITION_DEPENDENCY",
            "PUML_COMPOSITION_DEPENDENCY_CHECKED",
            "PUML_AGGREGATION_DEPENDENCY",
            "PUML_AGGREGATION_DEPENDENCY_CHECKED",
            "PUML_USE_DEPENDENCY",
            "PUML_USE_DEPENDENCY_CHECKED",
        } and args:
            current["dependencies"].append(PumlDependency(
                target=args[0],
                macro=name,
                line=line_number,
                checked=name.endswith("_CHECKED"),
                multiplicity_from=args[1] if len(args) > 1 else None,
                multiplicity_to=args[2] if len(args) > 2 else None,
                label=args[3] if len(args) > 3 else None,
            ))
    return tuple(classes)


def _preprocessor_directive(line: str) -> tuple[str, str] | None:
    stripped = line.strip()
    if not stripped.startswith("#"):
        return None
    tokens = stripped[1:].strip().split(None, 1)
    if not tokens:
        return None
    directive = tokens[0]
    rest = tokens[1].strip() if len(tokens) > 1 else ""
    if directive in {"if", "ifdef", "ifndef", "elif", "else", "endif"}:
        return directive, rest
    return None


def _update_active_stack(active_stack: list[tuple[bool, bool, bool]],
                         directive: tuple[str, str],
                         defined_macros: frozenset[str]) -> None:
    name, expression = directive
    if name in {"if", "ifdef", "ifndef"}:
        parent_active = _is_preprocessor_active(active_stack)
        condition_active = _evaluate_preprocessor_condition(name, expression, defined_macros)
        active_stack.append((parent_active, condition_active, condition_active))
        return
    if not active_stack:
        return
    parent_active, current_active, branch_taken = active_stack.pop()
    if name == "else":
        next_active = parent_active and not branch_taken
        active_stack.append((parent_active, next_active, True))
        return
    if name == "elif":
        condition_active = _evaluate_preprocessor_condition("if", expression, defined_macros)
        next_active = parent_active and not branch_taken and condition_active
        active_stack.append((parent_active, next_active, branch_taken or condition_active))
        return
    if name == "endif":
        return
    active_stack.append((parent_active, current_active, branch_taken))


def _is_preprocessor_active(active_stack: list[tuple[bool, bool, bool]]) -> bool:
    return all(parent_active and current_active for parent_active, current_active, _ in active_stack)


def _evaluate_preprocessor_condition(name: str,
                                     expression: str,
                                     defined_macros: frozenset[str]) -> bool:
    if name == "ifdef":
        return expression.split(None, 1)[0] in defined_macros
    if name == "ifndef":
        return expression.split(None, 1)[0] not in defined_macros
    stripped = expression.strip()
    if stripped.startswith("defined(") and stripped.endswith(")"):
        return stripped[len("defined("):-1].strip() in defined_macros
    if stripped.startswith("!defined(") and stripped.endswith(")"):
        return stripped[len("!defined("):-1].strip() not in defined_macros
    if stripped.startswith("defined "):
        return stripped.split(None, 1)[1].strip() in defined_macros
    if stripped.startswith("!defined "):
        return stripped.split(None, 1)[1].strip() not in defined_macros
    return stripped not in {"", "0"}


def _parse_macro_call(line: str) -> tuple[str, list[str]] | None:
    stripped = line.strip()
    if not stripped.startswith("PUML_"):
        return None
    open_index = stripped.find("(")
    close_index = stripped.rfind(")")
    if open_index < 0 or close_index < open_index:
        return None
    name = stripped[:open_index].strip()
    args = _split_macro_args(stripped[open_index + 1:close_index])
    return name, args


def _split_macro_args(text: str) -> list[str]:
    args: list[str] = []
    depth = 0
    start = 0
    for index, char in enumerate(text):
        if char in "([{<":
            depth += 1
        elif char in ")]}>":
            depth = max(depth - 1, 0)
        elif char == "," and depth == 0:
            args.append(text[start:index].strip())
            start = index + 1
    tail = text[start:].strip()
    if tail:
        args.append(tail)
    return args


def _class_symbol_index(symbols: tuple[CppSymbol, ...]) -> dict[str, CppSymbol]:
    result: dict[str, CppSymbol] = {}
    for symbol in _flatten_symbols(symbols):
        if symbol.kind in {"CLASS_DECL", "STRUCT_DECL", "CLASS_TEMPLATE"}:
            result[symbol.qualified_name] = symbol
            result.setdefault(symbol.name, symbol)
    return result


def _find_class_symbol(index: dict[str, CppSymbol], name: str) -> CppSymbol | None:
    if name in index:
        return index[name]
    short = _short_type_name(name)
    return index.get(short)


def _collect_translation_unit_class_relations(cursor: Any,
                                              source_file: Path,
                                              target_class_names: tuple[str, ...]) -> dict[str, PumlClassRelations]:
    result: dict[str, PumlClassRelations] = {}
    target_names = set(target_class_names)
    target_names.update(_short_type_name(name) for name in target_class_names)
    _collect_translation_unit_class_relations_into(cursor, source_file, result, target_names)
    _expand_class_relations_with_bases(result)
    return result


def _collect_translation_unit_class_relations_into(cursor: Any,
                                                  source_file: Path,
                                                  result: dict[str, PumlClassRelations],
                                                  target_names: set[str]) -> None:
    for child in cursor.get_children():
        kind = child.kind.name
        if kind in {"CLASS_DECL", "STRUCT_DECL", "CLASS_TEMPLATE"}:
            name = child.spelling or child.displayname
            if name and (name in target_names
                         or _short_type_name(name) in target_names
                         or _is_generated_ui_class(name)):
                qualified = _qualified_name(child, (), name)
                bases = _base_names(child)
                related_types = _cursor_related_types(child)
                _add_class_relations(result, qualified, bases, related_types)
                _add_class_relations(result, name, bases, related_types)
        parent_name = _semantic_parent_class_name(child)
        if parent_name and (parent_name in target_names or _short_type_name(parent_name) in target_names):
            _add_class_relations(result, parent_name, (), _cursor_related_types(child))
        if kind == "FUNCTION_DECL" and _is_from_file(child, source_file):
            related_types = _cursor_related_types(child)
            for target_name in target_names:
                if _has_related_type(related_types, target_name):
                    _add_class_relations(result, target_name, (), related_types)
        _collect_translation_unit_class_relations_into(child, source_file, result, target_names)


def _is_generated_ui_class(name: str) -> bool:
    return name.startswith("Ui_")


def _expand_class_relations_with_bases(index: dict[str, PumlClassRelations]) -> None:
    changed = True
    while changed:
        changed = False
        for name, relations in tuple(index.items()):
            related_types = set(relations.related_types)
            for base_name in relations.bases:
                base_relations = _find_class_relations(index, base_name)
                if base_relations is None:
                    continue
                related_types.update(base_relations.related_types)
            if related_types != set(relations.related_types):
                index[name] = PumlClassRelations(
                    bases=relations.bases,
                    related_types=tuple(sorted(related_types)),
                )
                changed = True


def _add_class_relations(result: dict[str, PumlClassRelations],
                         name: str,
                         bases: tuple[str, ...],
                         related_types: tuple[str, ...]) -> None:
    existing = result.get(name)
    if existing is None:
        result[name] = PumlClassRelations(bases=tuple(sorted(set(bases))),
                                          related_types=tuple(sorted(set(related_types))))
        return
    result[name] = PumlClassRelations(
        bases=tuple(sorted(set(existing.bases).union(bases))),
        related_types=tuple(sorted(set(existing.related_types).union(related_types))),
    )


def _find_class_relations(index: dict[str, PumlClassRelations], name: str) -> PumlClassRelations | None:
    if name in index:
        return index[name]
    return index.get(_short_type_name(name))


def _short_type_name(name: str) -> str:
    return name.strip().split("<", 1)[0].split("::")[-1]


def _semantic_parent_class_name(cursor: Any) -> str | None:
    parent = getattr(cursor, "semantic_parent", None)
    if parent is None:
        return None
    if parent.kind.name not in {"CLASS_DECL", "STRUCT_DECL", "CLASS_TEMPLATE"}:
        return None
    return parent.spelling or parent.displayname or None


def _cursor_related_types(cursor: Any) -> tuple[str, ...]:
    related_types: set[str] = set()
    _collect_cursor_related_types(cursor, related_types)
    return tuple(sorted(related_types))


def _collect_cursor_related_types(cursor: Any, related_types: set[str]) -> None:
    _add_cursor_type_spellings(cursor, related_types)
    if cursor.kind.name in {"TYPE_REF", "TEMPLATE_REF"}:
        _add_type_name(cursor.spelling, related_types)
        _add_type_name(cursor.displayname, related_types)
    for child in cursor.get_children():
        _collect_cursor_related_types(child, related_types)


def _add_cursor_type_spellings(cursor: Any, related_types: set[str]) -> None:
    for attr_name in ("type", "result_type"):
        try:
            type_obj = getattr(cursor, attr_name)
        except Exception:
            continue
        _add_type_spellings(type_obj, related_types)


def _add_type_spellings(type_obj: Any,
                        related_types: set[str],
                        *,
                        expand_declaration: bool = True) -> None:
    if type_obj is None:
        return
    try:
        _add_type_name(type_obj.spelling, related_types)
        _add_type_name_tokens(type_obj.spelling, related_types)
    except Exception:
        pass
    try:
        canonical = type_obj.get_canonical()
    except Exception:
        canonical = None
    if canonical is not None and canonical is not type_obj:
        try:
            _add_type_name(canonical.spelling, related_types)
            _add_type_name_tokens(canonical.spelling, related_types)
        except Exception:
            pass
    try:
        declaration = type_obj.get_declaration()
    except Exception:
        declaration = None
    if declaration is not None:
        _add_type_name(declaration.spelling, related_types)
        _add_type_name(declaration.displayname, related_types)
        if expand_declaration:
            _add_declaration_member_types(declaration, related_types)


def _add_declaration_member_types(declaration: Any, related_types: set[str]) -> None:
    if declaration.kind.name not in {"CLASS_DECL", "STRUCT_DECL", "CLASS_TEMPLATE"}:
        return
    if _is_system_cursor(declaration):
        return
    for child in declaration.get_children():
        if child.kind.name in {"FIELD_DECL", "PARM_DECL", "TYPE_REF"}:
            _add_cursor_type_spellings_no_declaration_expansion(child, related_types)


def _add_cursor_type_spellings_no_declaration_expansion(cursor: Any, related_types: set[str]) -> None:
    for attr_name in ("type", "result_type"):
        try:
            type_obj = getattr(cursor, attr_name)
        except Exception:
            continue
        _add_type_spellings(type_obj, related_types, expand_declaration=False)


def _is_system_cursor(cursor: Any) -> bool:
    location_file = getattr(cursor.location, "file", None)
    if location_file is None:
        return False
    path = Path(str(location_file)).resolve()
    if str(path).startswith("/usr/") or str(path).startswith("/opt/"):
        return True
    try:
        path.relative_to(Path.cwd().resolve())
    except ValueError:
        return True
    return False


def _add_type_name(name: str, related_types: set[str]) -> None:
    clean_name = name.strip()
    if not clean_name:
        return
    related_types.add(clean_name)
    short_name = _short_type_name(clean_name)
    if short_name:
        related_types.add(short_name)


def _add_type_name_tokens(name: str, related_types: set[str]) -> None:
    token = ""
    for char in name:
        if char.isalnum() or char in "_:":
            token += char
            continue
        _add_type_name_token(token, related_types)
        token = ""
    _add_type_name_token(token, related_types)


def _add_type_name_token(token: str, related_types: set[str]) -> None:
    clean_token = token.strip(":")
    if not clean_token or clean_token in {"const", "volatile", "class", "struct", "enum"}:
        return
    _add_type_name(clean_token, related_types)


def _has_related_type(related_types: tuple[str, ...], expected_type: str) -> bool:
    expected = expected_type.strip()
    expected_short = _short_type_name(expected)
    for related_type in related_types:
        if related_type == expected or _short_type_name(related_type) == expected_short:
            return True
    return False


def _related_types_summary(related_types: tuple[str, ...], *, limit: int = 20) -> str:
    sample = sorted(related_types)[:limit]
    suffix = "" if len(related_types) <= limit else f", ... +{len(related_types) - limit} more"
    return f"(count={len(related_types)}, sample={sample}{suffix})"


def _puml_audit_payload(result: PumlAuditResult) -> dict[str, Any]:
    return {
        "file_path": str(result.file_path),
        "ok": result.ok,
        "classes": [
            {
                "name": class_block.name,
                "kind": class_block.kind,
                "line": class_block.line,
                "package": class_block.package,
                "checked": class_block.checked,
                "inheritances": [
                    {"base": base, "line": line, "checked": checked}
                    for base, line, checked in class_block.inheritances
                ],
                "dependencies": [asdict(dependency) for dependency in class_block.dependencies],
            }
            for class_block in result.classes
        ],
        "findings": [asdict(finding) for finding in result.findings],
    }


def _add_include_to_source(file_path: Path,
                           source: str,
                           statement: str,
                           *,
                           check_only: bool) -> tuple[EditResult, str]:
    rendered = _normalize_include(statement)
    existing = {_normalize_include(line) for line in source.splitlines()
                if line.strip().startswith("#include")}
    if rendered in existing:
        return (EditResult(file_path=file_path,
                           operation="includes-add",
                           target=rendered,
                           changed=False,
                           check_only=check_only,
                           statement=rendered),
                source)
    line_offsets = _line_start_offsets(source)
    insert_line = _include_insert_line(source)
    insert_offset = line_offsets[insert_line - 1] if line_offsets else 0
    new_source = source[:insert_offset] + rendered + "\n" + source[insert_offset:]
    return (EditResult(file_path=file_path,
                       operation="includes-add",
                       target=rendered,
                       changed=True,
                       check_only=check_only,
                       insert_line=insert_line,
                       statement=rendered,
                       diff=_render_unified_diff(source, new_source, file_path)),
            new_source)


def _normalized_batch_plan(plan: object) -> dict[str, object]:
    if isinstance(plan, list):
        operations = plan
        check_only = False
    elif isinstance(plan, dict):
        operations = plan.get("operations")
        check_only = plan.get("check_only", False)
    else:
        raise ValueError("batch plan must be a JSON object or array")
    if not isinstance(operations, list):
        raise ValueError("batch plan must include an 'operations' list")
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ValueError(f"batch operation #{index + 1} must be an object")
    return {"operations": operations, "check_only": bool(check_only)}


def _apply_batch_operation(operation: dict[str, object],
                           staged_sources: dict[Path, tuple[str, str]],
                           compile_db: Path | None,
                           *,
                           clang_args: tuple[str, ...],
                           check_only: bool,
                           operation_index: int) -> tuple[EditResult, str, str]:
    command = _required_batch_string(operation, "command", operation_index)
    file_path = _batch_file_path(operation, operation_index=operation_index)
    source, encoding = staged_sources.get(file_path, _read_source_with_encoding(file_path))
    if command in {"replace-symbol", "replace-symbol-body"}:
        result, new_source = _apply_symbol_edit_to_source(file_path,
                                                          source,
                                                          _required_batch_string(operation, "symbol", operation_index),
                                                          _required_batch_string(operation,
                                                                                 "expect_hash",
                                                                                 operation_index),
                                                          _required_batch_string(operation,
                                                                                 "replacement_text",
                                                                                 operation_index),
                                                          compile_db,
                                                          clang_args=clang_args,
                                                          operation=command,
                                                          scope="body" if command.endswith("-body") else "node",
                                                          check_only=check_only)
        return result, new_source, encoding
    if command in {"insert-before-symbol", "insert-after-symbol"}:
        position = "before" if command == "insert-before-symbol" else "after"
        result, new_source = _insert_relative_to_symbol_in_source(file_path,
                                                                  source,
                                                                  _required_batch_string(operation,
                                                                                         "symbol",
                                                                                         operation_index),
                                                                  _required_batch_string(operation,
                                                                                         "expect_hash",
                                                                                         operation_index),
                                                                  _required_batch_string(operation,
                                                                                         "snippet_text",
                                                                                         operation_index),
                                                                  compile_db,
                                                                  clang_args=clang_args,
                                                                  position=position,
                                                                  check_only=check_only)
        return result, new_source, encoding
    if command == "includes-add":
        result, new_source = _add_include_to_source(file_path,
                                                    source,
                                                    _required_batch_string(operation,
                                                                           "include_statement",
                                                                           operation_index),
                                                    check_only=check_only)
        return result, new_source, encoding
    raise ValueError(f"unsupported batch command in operation #{operation_index + 1}: {command}")


def _apply_symbol_edit_to_source(file_path: Path,
                                 source: str,
                                 symbol_name: str,
                                 expected_hash: str,
                                 replacement_text: str,
                                 compile_db: Path | None,
                                 *,
                                 clang_args: tuple[str, ...],
                                 operation: str,
                                 scope: str,
                                 check_only: bool) -> tuple[EditResult, str]:
    _, symbols, _ = _parse_symbols_from_source(file_path,
                                               source,
                                               compile_db,
                                               clang_args)
    symbol = _resolve_symbol(symbols, symbol_name, file_path)
    snapshot = _snapshot_for_symbol(symbol)
    span = symbol.span if scope == "node" else symbol.body_span
    current_hash = symbol.hash if scope == "node" else symbol.body_hash
    if span is None or current_hash is None:
        raise CppCodeMapError(f"symbol has no replaceable {scope}: {symbol.qualified_name}",
                              details={"file": str(file_path), "symbol": symbol.qualified_name})
    if current_hash != expected_hash:
        raise CppCodeMapError(
            f"symbol {scope} hash mismatch: expected={expected_hash} actual={current_hash}",
            details={"file": str(file_path),
                     "symbol": symbol.qualified_name,
                     "expected_hash": expected_hash,
                     "actual_hash": current_hash,
                     "snapshot": _snapshot_payload(snapshot)},
        )
    new_source = source[:span.start_offset] + _normalize_block(replacement_text) + source[span.end_offset:]
    _validate_cpp_source(file_path, new_source, compile_db, clang_args, symbol=symbol.qualified_name)
    _, new_symbols, _ = _parse_symbols_from_source(file_path, new_source, compile_db, clang_args)
    new_symbol = _resolve_symbol(new_symbols, symbol_name, file_path)
    new_hash = new_symbol.hash if scope == "node" else new_symbol.body_hash
    return (EditResult(file_path=file_path,
                       operation=operation,
                       target=new_symbol.qualified_name,
                       changed=source != new_source,
                       check_only=check_only,
                       old_hash=current_hash,
                       new_hash=new_hash,
                       snapshot=_snapshot_for_symbol(new_symbol),
                       diff=_render_unified_diff(source, new_source, file_path)),
            new_source)


def _insert_relative_to_symbol_in_source(file_path: Path,
                                         source: str,
                                         symbol_name: str,
                                         expected_hash: str,
                                         snippet_text: str,
                                         compile_db: Path | None,
                                         *,
                                         clang_args: tuple[str, ...],
                                         position: str,
                                         check_only: bool) -> tuple[EditResult, str]:
    _, symbols, _ = _parse_symbols_from_source(file_path, source, compile_db, clang_args)
    symbol = _resolve_symbol(symbols, symbol_name, file_path)
    snapshot = _snapshot_for_symbol(symbol)
    if symbol.hash != expected_hash:
        raise CppCodeMapError(
            f"anchor symbol hash mismatch: expected={expected_hash} actual={symbol.hash}",
            details={"file": str(file_path),
                     "symbol": symbol.qualified_name,
                     "expected_hash": expected_hash,
                     "actual_hash": symbol.hash,
                     "snapshot": _snapshot_payload(snapshot)},
        )
    line_offsets = _line_start_offsets(source)
    if position == "before":
        insert_offset = line_offsets[symbol.span.start_line - 1]
        insert_line = symbol.span.start_line
    else:
        insert_offset = symbol.span.end_offset
        if source[insert_offset:insert_offset + 1] == "\n":
            insert_offset += 1
        insert_line = symbol.span.end_line + 1
    new_source = source[:insert_offset] + _normalize_block(snippet_text) + source[insert_offset:]
    _validate_cpp_source(file_path, new_source, compile_db, clang_args, symbol=symbol.qualified_name)
    return (EditResult(file_path=file_path,
                       operation=f"insert-{position}-symbol",
                       target=symbol.qualified_name,
                       changed=source != new_source,
                       check_only=check_only,
                       old_hash=symbol.hash,
                       new_hash=symbol.hash,
                       snapshot=snapshot,
                       insert_line=insert_line,
                       diff=_render_unified_diff(source, new_source, file_path)),
            new_source)


def _batch_file_path(operation: dict[str, object], *, operation_index: int) -> Path:
    value = operation.get("file_path") or operation.get("cpp_file")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"batch operation #{operation_index + 1} requires non-empty 'file_path'")
    return Path(value).resolve()


def _required_batch_string(operation: dict[str, object], field_name: str, operation_index: int) -> str:
    value = operation.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"batch operation #{operation_index + 1} requires non-empty '{field_name}'")
    return value


def _validate_cpp_source(file_path: Path,
                         source: str,
                         compile_db: Path | None,
                         clang_args: tuple[str, ...],
                         *,
                         symbol: str | None = None) -> None:
    _, _, diagnostics = _parse_symbols_from_source(file_path, source, compile_db, clang_args)
    errors = [diagnostic for diagnostic in diagnostics if " error: " in diagnostic.lower()]
    if errors:
        raise CppCodeMapError("replacement produced invalid C++",
                              details={"file": str(file_path),
                                       "symbol": symbol,
                                       "diagnostics": errors})


def _parse_symbols(file_path: Path,
                   compile_db: Path | None,
                   extra_args: tuple[str, ...],
                   *,
                   original_file: Path | None = None) -> tuple[str, tuple[CppSymbol, ...], tuple[str, ...]]:
    clang = _load_clang()
    source = _read_source(file_path)
    compile_target = original_file or file_path
    args = _compile_args(compile_target, compile_db, extra_args)
    index = clang.Index.create()
    try:
        translation_unit = index.parse(str(file_path),
                                       args=args,
                                       options=clang.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
    except Exception as exc:  # pragma: no cover - depends on local libclang.
        raise CppCodeMapError(f"failed to parse {file_path}: {exc}",
                              details={"file": str(file_path), "args": args}) from exc
    diagnostics = tuple(str(diagnostic) for diagnostic in translation_unit.diagnostics)
    symbols = tuple(_collect_symbols(translation_unit.cursor, file_path, source, ()))
    return source, symbols, diagnostics


def _load_clang():
    try:
        from clang import cindex
    except ImportError as exc:
        raise CppCodeMapError(
            "clang Python bindings are not installed. Install python3-clang or the clang PyPI package.",
            details={"missing": "clang.cindex"},
        ) from exc
    library_file = os.environ.get("LIBCLANG_LIBRARY_FILE")
    if library_file:
        cindex.Config.set_library_file(library_file)
    library_path = os.environ.get("LIBCLANG_LIBRARY_PATH")
    if library_path:
        cindex.Config.set_library_path(library_path)
    return cindex


def _compile_args(file_path: Path,
                  compile_db: Path | None,
                  extra_args: tuple[str, ...]) -> list[str]:
    compile_commands = _find_compile_commands(file_path, compile_db)
    if not compile_commands:
        language = _language_for_file(file_path)
        return ["-x", language, "-std=c++17",
                *_implicit_include_args("c++", language),
                *extra_args]
    entries = json.loads(compile_commands.read_text(encoding="utf-8"))
    target = file_path.resolve()
    for entry in entries:
        directory = _remap_compile_path(Path(entry.get("directory", ".")), compile_commands).resolve()
        candidate = _remap_compile_path(Path(entry.get("file", "")), compile_commands, directory).resolve()
        if candidate == target:
            args = _arguments_from_entry(entry, directory, target, compile_commands)
            language = _language_for_file(file_path)
            compiler = _compiler_from_entry(entry)
            return [*_target_args(compiler),
                    *args,
                    *_implicit_include_args(compiler, language),
                    *extra_args]
    language = _language_for_file(file_path)
    return ["-x", language, "-std=c++17",
            *_implicit_include_args("c++", language),
            *extra_args]


def _find_compile_commands(file_path: Path, compile_db: Path | None) -> Path | None:
    if compile_db:
        if compile_db.is_file():
            return compile_db
        candidate = compile_db / "compile_commands.json"
        if candidate.is_file():
            return candidate
        raise CppCodeMapError("compile database was not found",
                              details={"compile_db": str(compile_db)})
    for parent in (file_path.resolve().parent, *file_path.resolve().parents):
        candidate = parent / "compile_commands.json"
        if candidate.is_file():
            return candidate
    return None


def _arguments_from_entry(entry: dict[str, Any],
                          directory: Path,
                          source: Path,
                          compile_commands: Path) -> list[str]:
    raw_args = entry.get("arguments")
    if raw_args is None:
        raw_args = shlex.split(entry.get("command", ""))
    args = list(raw_args)[1:]
    cleaned: list[str] = []
    skip_next = False
    options_with_value = {"-o", "-MF", "-MT", "-MQ", "--param"}
    gcc_only_prefixes = (
        "-fmacro-prefix-map=",
        "-moverride=",
        "-specs=",
        "--param=",
    )
    gcc_only_args = {
        "-fno-reorder-functions",
        "-fno-defer-pop",
    }
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in options_with_value:
            skip_next = True
            continue
        if arg == "-c":
            continue
        if arg in gcc_only_args or arg.startswith(gcc_only_prefixes):
            continue
        remapped = _remap_arg_path(arg, compile_commands, directory)
        if remapped.startswith("--sysroot=") and not Path(remapped.removeprefix("--sysroot=")).is_dir():
            continue
        if remapped.startswith("-mabi="):
            continue
        if (directory / remapped).resolve() == source or Path(remapped).resolve() == source:
            continue
        cleaned.append(remapped)
    return cleaned


def _remap_arg_path(arg: str, compile_commands: Path, directory: Path) -> str:
    for prefix in ("-I", "-isystem", "-imacros"):
        if arg.startswith(prefix) and len(arg) > len(prefix):
            return prefix + str(_remap_compile_path(Path(arg[len(prefix):]), compile_commands, directory))
    if arg.startswith("--sysroot="):
        return "--sysroot=" + str(_remap_compile_path(Path(arg.removeprefix("--sysroot=")),
                                                      compile_commands,
                                                      directory))
    if arg.startswith("-"):
        return arg
    return str(_remap_compile_path(Path(arg), compile_commands, directory))


def _remap_compile_path(path: Path, compile_commands: Path, directory: Path | None = None) -> Path:
    if not path.is_absolute():
        return (directory / path) if directory else path

    build_dir = compile_commands.parent.resolve()
    raw_root = Path(os.environ.get("CODEX_CPP_CODE_MAP_RAW_WORKSPACE", "/workspace"))
    raw_build_dir = raw_root / build_dir.parent.name / build_dir.name
    raw_workspace = raw_build_dir.parents[1]
    host_workspace = build_dir.parents[1]

    try:
        return host_workspace / path.relative_to(raw_workspace)
    except ValueError:
        return path


def _defined_macros(args: list[str]) -> frozenset[str]:
    macros: set[str] = set()
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-D" and index + 1 < len(args):
            macros.add(args[index + 1].split("=", 1)[0])
            index += 2
            continue
        if arg.startswith("-D") and len(arg) > 2:
            macros.add(arg[2:].split("=", 1)[0])
        index += 1
    return frozenset(macros)


def _compiler_from_entry(entry: dict[str, Any]) -> str:
    raw_args = entry.get("arguments")
    if raw_args:
        return str(raw_args[0])
    command = shlex.split(entry.get("command", ""))
    if command:
        return command[0]
    return "c++"


def _target_args(compiler: str) -> tuple[str, ...]:
    compiler_name = Path(compiler).name
    if compiler_name.startswith("aarch64-zephyr-elf-"):
        return ("--target=aarch64-zephyr-elf",)
    if compiler_name.startswith("arm-zephyr-eabi-"):
        return ("--target=arm-zephyr-eabi",)
    if compiler_name.startswith("riscv64-zephyr-elf-"):
        return ("--target=riscv64-zephyr-elf",)
    return ()


@lru_cache(maxsize=16)
def _implicit_include_args(compiler: str, language: str) -> tuple[str, ...]:
    try:
        result = subprocess.run([compiler, "-E", "-x", language, "-", "-v"],
                                input="",
                                capture_output=True,
                                check=False,
                                text=True,
                                timeout=10)
    except (OSError, subprocess.SubprocessError):
        if compiler != "cc":
            return _implicit_include_args("cc", language)
        return ()
    lines = (result.stderr + result.stdout).splitlines()
    include_dirs: list[str] = []
    in_search_list = False
    for line in lines:
        stripped = line.strip()
        if stripped == "#include <...> search starts here:":
            in_search_list = True
            continue
        if stripped == "End of search list.":
            break
        if in_search_list:
            directory = stripped.removesuffix(" (framework directory)")
            if Path(directory).is_dir():
                include_dirs.extend(("-isystem", directory))
    return tuple(include_dirs)


def _collect_symbols(cursor: Any,
                     file_path: Path,
                     source: str,
                     parents: tuple[str, ...]) -> list[CppSymbol]:
    symbols: list[CppSymbol] = []
    for child in cursor.get_children():
        if not _is_from_file(child, file_path):
            symbols.extend(_collect_symbols(child, file_path, source, parents))
            continue
        kind = child.kind.name
        name = child.spelling or child.displayname
        next_parents = parents
        if kind in SYMBOL_KINDS and name:
            qualified = _qualified_name(child, parents, name)
            if kind in {"NAMESPACE", "CLASS_DECL", "STRUCT_DECL", "CLASS_TEMPLATE"}:
                next_parents = (*parents, name)
            else:
                next_parents = parents
            body_span = _body_span_from_cursor(source, child)
            symbol = CppSymbol(name=name,
                               qualified_name=qualified,
                               kind=kind,
                               span=_span_from_cursor(child),
                               body_span=body_span,
                               hash=_hash_span(source, child.extent),
                               body_hash=None if body_span is None else _hash_source_span(source, body_span),
                               bases=_base_names(child),
                               children=tuple(_collect_symbols(child, file_path, source, next_parents)))
            symbols.append(symbol)
        else:
            symbols.extend(_collect_symbols(child, file_path, source, next_parents))
    return symbols


def _is_from_file(cursor: Any, file_path: Path) -> bool:
    location = cursor.location
    if not location or not location.file:
        return False
    return Path(str(location.file)).resolve() == file_path.resolve()


def _base_names(cursor: Any) -> tuple[str, ...]:
    if cursor.kind.name not in {"CLASS_DECL", "STRUCT_DECL", "CLASS_TEMPLATE"}:
        return ()
    bases: list[str] = []
    for child in cursor.get_children():
        if child.kind.name == "CXX_BASE_SPECIFIER":
            name = child.spelling or child.displayname
            if name:
                bases.append(name)
    return tuple(bases)


def _span_from_cursor(cursor: Any) -> SourceSpan:
    extent = cursor.extent
    return SourceSpan(start_line=extent.start.line,
                      start_column=extent.start.column,
                      end_line=extent.end.line,
                      end_column=extent.end.column,
                      start_offset=extent.start.offset,
                      end_offset=extent.end.offset)


def _body_span_from_cursor(source: str, cursor: Any) -> SourceSpan | None:
    if cursor.kind.name not in {"FUNCTION_DECL", "CXX_METHOD", "CONSTRUCTOR", "DESTRUCTOR"}:
        return None
    start = cursor.extent.start.offset
    end = cursor.extent.end.offset
    open_brace = source.find("{", start, end)
    if open_brace < 0:
        return None
    close_brace = _matching_brace_offset(source, open_brace, end)
    if close_brace is None:
        return None
    body_start = open_brace + 1
    body_end = close_brace
    return _span_from_offsets(source, body_start, body_end)


def _span_from_offsets(source: str, start_offset: int, end_offset: int) -> SourceSpan:
    starts = _line_start_offsets(source)
    start_line, start_column = _line_column_from_offset(starts, start_offset)
    end_line, end_column = _line_column_from_offset(starts, end_offset)
    return SourceSpan(start_line=start_line,
                      start_column=start_column,
                      end_line=end_line,
                      end_column=end_column,
                      start_offset=start_offset,
                      end_offset=end_offset)


def _line_column_from_offset(line_offsets: list[int], offset: int) -> tuple[int, int]:
    line_index = 0
    for index, line_offset in enumerate(line_offsets):
        if line_offset > offset:
            break
        line_index = index
    return line_index + 1, offset - line_offsets[line_index] + 1


def _matching_brace_offset(source: str, open_brace: int, limit: int) -> int | None:
    depth = 0
    for index in range(open_brace, limit):
        char = source[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _hash_span(source: str, extent: Any) -> str:
    text = source[extent.start.offset:extent.end.offset]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_source_span(source: str, span: SourceSpan) -> str:
    text = source[span.start_offset:span.end_offset]
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _flatten_symbols(symbols: tuple[CppSymbol, ...]) -> list[CppSymbol]:
    flat: list[CppSymbol] = []
    for symbol in symbols:
        flat.append(symbol)
        flat.extend(_flatten_symbols(symbol.children))
    return flat


def _render_symbol(symbol: CppSymbol, depth: int) -> list[str]:
    indent = "  " * depth
    lines = [f"{indent}{symbol.kind.lower()} {symbol.qualified_name}: {_span_text(symbol.span)}"]
    for child in symbol.children:
        lines.extend(_render_symbol(child, depth + 1))
    return lines


def _symbol_payload(symbol: CppSymbol) -> dict[str, Any]:
    return {
        "name": symbol.name,
        "qualified_name": symbol.qualified_name,
        "kind": symbol.kind,
        "span": asdict(symbol.span),
        "body_span": None if symbol.body_span is None else asdict(symbol.body_span),
        "hash": symbol.hash,
        "body_hash": symbol.body_hash,
        "children": [_symbol_payload(child) for child in symbol.children],
    }


def _snapshot_payload(snapshot: SymbolSnapshot) -> dict[str, Any]:
    payload = asdict(snapshot)
    payload["span"] = asdict(snapshot.span)
    payload["body_span"] = None if snapshot.body_span is None else asdict(snapshot.body_span)
    return payload


def _edit_result_payload(result: EditResult) -> dict[str, Any]:
    return {
        "file_path": str(result.file_path),
        "operation": result.operation,
        "target": result.target,
        "changed": result.changed,
        "check_only": result.check_only,
        "old_hash": result.old_hash,
        "new_hash": result.new_hash,
        "insert_line": result.insert_line,
        "statement": result.statement,
        "snapshot": None if result.snapshot is None else _snapshot_payload(result.snapshot),
        "diff": result.diff,
    }


def _span_text(span: SourceSpan) -> str:
    return f"{span.start_line}:{span.start_column}-{span.end_line}:{span.end_column}"


def _read_source(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8", errors="replace")


def _read_source_with_encoding(file_path: Path) -> tuple[str, str]:
    return file_path.read_text(encoding="utf-8", errors="replace"), "utf-8"


def _line_start_offsets(source: str) -> list[int]:
    offsets = [0]
    for index, char in enumerate(source):
        if char == "\n":
            offsets.append(index + 1)
    return offsets


def _normalize_block(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.endswith("\n"):
        normalized += "\n"
    return normalized


def _normalize_include(statement: str) -> str:
    normalized = statement.strip()
    if not normalized:
        raise ValueError("include statement is empty")
    if normalized.startswith("#include"):
        return normalized
    return f"#include {normalized}"


def _include_insert_line(source: str) -> int:
    insert_line = 1
    for index, line in enumerate(source.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("#pragma once") or stripped.startswith("#include"):
            insert_line = index + 1
            continue
        if not stripped or stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        break
    return insert_line


def _render_unified_diff(old_source: str, new_source: str, file_path: Path) -> str | None:
    if old_source == new_source:
        return None
    diff = difflib.unified_diff(old_source.splitlines(),
                                new_source.splitlines(),
                                fromfile=f"{file_path} (before)",
                                tofile=f"{file_path} (after)",
                                lineterm="")
    diff_text = "\n".join(diff)
    return diff_text or None


def _atomic_write_text(file_path: Path, text: str, encoding: str) -> None:
    temp_path = file_path.with_name(f"{file_path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(text, encoding=encoding)
        os.replace(temp_path, file_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _qualified_name(cursor: Any, parents: tuple[str, ...], fallback_name: str) -> str:
    names: list[str] = []
    current = cursor.semantic_parent
    while current is not None and getattr(current, "kind", None) is not None:
        kind_name = current.kind.name
        spelling = current.spelling or current.displayname
        if kind_name == "TRANSLATION_UNIT":
            break
        if spelling:
            names.append(spelling)
        current = current.semantic_parent
    if names:
        return "::".join((*reversed(names), fallback_name))
    return "::".join((*parents, fallback_name))


def _symbol_signature(symbol: CppSymbol) -> str:
    return symbol.qualified_name.split("::")[-1]


def _language_for_file(file_path: Path) -> str:
    if file_path.suffix.lower() in {".c"}:
        return "c"
    return "c++"
