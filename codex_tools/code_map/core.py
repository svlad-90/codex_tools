from __future__ import annotations

import ast
import builtins
import difflib
import hashlib
import json
import os
import textwrap
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class CodeMapNode:
    kind: str
    name: str
    qualified_name: str
    start_line: int
    end_line: int
    children: tuple["CodeMapNode", ...]


@dataclass(frozen=True)
class CodeMapReport:
    file_path: Path
    nodes: tuple[CodeMapNode, ...]


@dataclass(frozen=True)
class SourceSpan:
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class SymbolSnapshot:
    file_path: Path
    module_name: str
    kind: str
    name: str
    qualified_name: str
    local_qualified_name: str
    start_line: int
    end_line: int
    shape_hash: str
    node_hash: str
    node_source: str
    body_hash: str | None
    body_source: str | None
    body_start_line: int | None
    body_end_line: int | None
    body_indent_columns: int | None


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
    file_path: Path
    ok: bool
    error_message: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class CodeMapErrorDetails:
    code: str
    message: str
    file_path: Path | None = None
    symbol: str | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None
    line: int | None = None
    column: int | None = None
    current_snapshot: SymbolSnapshot | None = None


class CodeMapEditError(ValueError):
    def __init__(self, details: CodeMapErrorDetails) -> None:
        super().__init__(details.message)
        self.details = details


@dataclass(frozen=True)
class ClassField:
    name: str
    annotation: str | None
    start_line: int
    inferred: bool = False


@dataclass(frozen=True)
class ClassMethod:
    name: str
    kind: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class ClassInfo:
    module_name: str
    qualified_name: str
    file_path: Path
    name: str
    start_line: int
    end_line: int
    bases: tuple[str, ...]
    fields: tuple[ClassField, ...]
    methods: tuple[ClassMethod, ...]


@dataclass(frozen=True)
class ClassRelation:
    kind: str
    source: str
    target: str
    label: str | None = None


@dataclass(frozen=True)
class ClassDiagramReport:
    target_path: Path
    classes: tuple[ClassInfo, ...]
    relations: tuple[ClassRelation, ...]


@dataclass(frozen=True)
class FacadeCallSite:
    file_path: Path
    line: int
    column: int
    receiver: str
    enclosing_symbol: str | None
    layer: str
    access_kind: str


@dataclass(frozen=True)
class FacadeDelegation:
    kind: str
    expression: str
    target: str | None
    target_group: str


@dataclass(frozen=True)
class FacadeMethodAudit:
    name: str
    start_line: int
    end_line: int
    visibility: str
    categories: tuple[str, ...]
    layer_counts: tuple[tuple[str, int], ...]
    delegation: FacadeDelegation | None
    call_sites: tuple[FacadeCallSite, ...]


@dataclass(frozen=True)
class FacadeAuditReport:
    file_path: Path
    symbol: str
    methods: tuple[FacadeMethodAudit, ...]
    caller_roots: tuple[Path, ...]


@dataclass(frozen=True)
class ProtocolContract:
    feature: str
    qualified_name: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class ProtocolMemberAudit:
    name: str
    kind: str
    start_line: int
    end_line: int
    categories: tuple[str, ...]
    owner_features: tuple[str, ...]
    replacement_contracts: tuple[str, ...]
    delegation: FacadeDelegation | None


@dataclass(frozen=True)
class ProtocolTypeAudit:
    file_path: Path
    name: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    bases: tuple[str, ...]
    base_contracts: tuple[str, ...]
    owner_features: tuple[str, ...]
    categories: tuple[str, ...]
    members: tuple[ProtocolMemberAudit, ...]


@dataclass(frozen=True)
class ProtocolAuditReport:
    target_path: Path
    file_path: Path | None
    symbol: str | None
    facade_file_path: Path | None
    facade_symbol: str | None
    classes: tuple[ProtocolTypeAudit, ...]


@dataclass(frozen=True)
class _SurfaceMemberSpec:
    name: str
    kind: str
    start_line: int
    end_line: int
    node: ast.AST | None


@dataclass(frozen=True)
class _SymbolSpec:
    kind: str
    name: str
    qualified_name: str
    local_qualified_name: str
    node_span: SourceSpan
    node_indent_text: str
    body_span: SourceSpan | None
    body_indent_text: str | None


def build_code_map(file_path: Path) -> CodeMapReport:
    source = file_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(file_path))
    nodes = tuple(_build_nodes(tree.body))
    return CodeMapReport(file_path=file_path, nodes=nodes)


def render_code_map(file_path: Path, project_root: Path | None = None) -> str:
    report = build_code_map(file_path)
    label = _display_path(report.file_path, project_root)
    lines = [label]
    for node in report.nodes:
        lines.extend(_render_node(node, depth=0))
    return "\n".join(lines)


def render_code_map_json(file_path: Path, project_root: Path | None = None) -> str:
    report = build_code_map(file_path)
    payload = {
        "file_path": _display_path(report.file_path, project_root),
        "nodes": [_code_map_node_payload(node) for node in report.nodes],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def build_symbol_snapshot(
    file_path: Path,
    project_root: Path,
    symbol: str,
) -> SymbolSnapshot:
    source = file_path.read_text(encoding="utf-8-sig")
    return _build_symbol_snapshot_from_source(file_path, project_root, symbol, source)


def render_symbol_snapshot(
    file_path: Path,
    project_root: Path,
    symbol: str,
) -> str:
    snapshot = build_symbol_snapshot(file_path, project_root, symbol)
    label = _display_path(snapshot.file_path, project_root)
    lines = [
        f"{label} :: symbol-get",
        f"symbol: {snapshot.local_qualified_name}",
        f"qualified: {snapshot.qualified_name}",
        f"kind: {snapshot.kind}",
        f"shape_hash: {snapshot.shape_hash}",
        f"node: {snapshot.start_line}-{snapshot.end_line} hash={snapshot.node_hash}",
    ]
    if snapshot.body_hash is not None:
        lines.append(
            "body: "
            + f"{snapshot.body_start_line}-{snapshot.body_end_line} "
            + f"indent={snapshot.body_indent_columns} hash={snapshot.body_hash}"
        )
    return "\n".join(lines)


def render_symbol_snapshot_json(
    file_path: Path,
    project_root: Path,
    symbol: str,
) -> str:
    snapshot = build_symbol_snapshot(file_path, project_root, symbol)
    return json.dumps(_symbol_snapshot_payload(snapshot, project_root), indent=2, sort_keys=True)


def replace_symbol(
    file_path: Path,
    project_root: Path,
    symbol: str,
    expected_hash: str,
    replacement_text: str,
    *,
    check_only: bool = False,
) -> EditResult:
    source, encoding = _read_source_with_encoding(file_path)
    result, new_source = _apply_symbol_edit_to_source(
        file_path,
        project_root,
        source,
        symbol,
        expected_hash,
        replacement_text,
        operation="replace-symbol",
        scope="node",
        check_only=check_only,
    )
    if not check_only:
        _atomic_write_text(file_path, new_source, encoding)
    return result


def replace_symbol_body(
    file_path: Path,
    project_root: Path,
    symbol: str,
    expected_hash: str,
    replacement_text: str,
    *,
    check_only: bool = False,
) -> EditResult:
    source, encoding = _read_source_with_encoding(file_path)
    result, new_source = _apply_symbol_edit_to_source(
        file_path,
        project_root,
        source,
        symbol,
        expected_hash,
        replacement_text,
        operation="replace-symbol-body",
        scope="body",
        check_only=check_only,
    )
    if not check_only:
        _atomic_write_text(file_path, new_source, encoding)
    return result


def insert_before_symbol(
    file_path: Path,
    project_root: Path,
    symbol: str,
    expected_hash: str,
    snippet_text: str,
    *,
    check_only: bool = False,
) -> EditResult:
    source, encoding = _read_source_with_encoding(file_path)
    result, new_source = _insert_relative_to_symbol_in_source(
        file_path,
        project_root,
        source,
        symbol,
        expected_hash,
        snippet_text,
        position="before",
        check_only=check_only,
    )
    if not check_only:
        _atomic_write_text(file_path, new_source, encoding)
    return result


def insert_after_symbol(
    file_path: Path,
    project_root: Path,
    symbol: str,
    expected_hash: str,
    snippet_text: str,
    *,
    check_only: bool = False,
) -> EditResult:
    source, encoding = _read_source_with_encoding(file_path)
    result, new_source = _insert_relative_to_symbol_in_source(
        file_path,
        project_root,
        source,
        symbol,
        expected_hash,
        snippet_text,
        position="after",
        check_only=check_only,
    )
    if not check_only:
        _atomic_write_text(file_path, new_source, encoding)
    return result


def add_import_statement(
    file_path: Path,
    statement: str,
    *,
    check_only: bool = False,
) -> EditResult:
    source, encoding = _read_source_with_encoding(file_path)
    result, new_source = _add_import_statement_to_source(
        file_path,
        source,
        statement,
        check_only=check_only,
    )
    if not check_only:
        _atomic_write_text(file_path, new_source, encoding)
    return result


def apply_batch_edits(
    plan: object,
    project_root: Path,
    *,
    check_only: bool = False,
) -> BatchEditResult:
    plan_payload = _normalized_batch_plan(plan)
    effective_check_only = check_only or bool(plan_payload.get("check_only", False))
    operations_payload = plan_payload["operations"]
    staged_sources: dict[Path, tuple[str, str]] = {}
    results: list[EditResult] = []
    for index, operation_payload in enumerate(operations_payload):
        result, new_source, encoding = _apply_batch_operation(
            operation_payload,
            project_root,
            staged_sources,
            check_only=effective_check_only,
            operation_index=index,
        )
        file_path = _resolve_batch_file_path(operation_payload, project_root, operation_index=index)
        staged_sources[file_path] = (new_source, encoding)
        results.append(result)
    if not effective_check_only:
        for file_path, (source, encoding) in staged_sources.items():
            if any(result.changed and result.file_path == file_path for result in results):
                _atomic_write_text(file_path, source, encoding)
    return BatchEditResult(
        operations=tuple(results),
        check_only=effective_check_only,
    )


def render_edit_result(
    result: EditResult,
    project_root: Path | None = None,
) -> str:
    payload = _edit_result_payload(result, project_root)
    head = f"{payload['file_path']} :: {result.operation}"
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
    rendered = head + " " + " ".join(parts)
    if result.diff:
        return rendered + "\n" + result.diff
    return rendered


def render_edit_result_json(result: EditResult, project_root: Path | None = None) -> str:
    return json.dumps(_edit_result_payload(result, project_root), indent=2, sort_keys=True)


def render_batch_edit_result(
    result: BatchEditResult,
    project_root: Path | None = None,
) -> str:
    changed_count = sum(1 for operation in result.operations if operation.changed)
    lines = [
        "code_map.py :: batch "
        + f"operations={len(result.operations)} "
        + f"changed={changed_count} "
        + f"check_only={str(result.check_only).lower()}",
    ]
    for operation in result.operations:
        lines.append("")
        lines.append(render_edit_result(operation, project_root))
    return "\n".join(lines)


def render_batch_edit_result_json(result: BatchEditResult, project_root: Path | None = None) -> str:
    return json.dumps(_batch_edit_result_payload(result, project_root), indent=2, sort_keys=True)


def parse_check(file_path: Path) -> ParseCheckResult:
    source = file_path.read_text(encoding="utf-8-sig")
    try:
        ast.parse(source, filename=str(file_path))
    except SyntaxError as error:
        line = None if error.lineno is None else int(error.lineno)
        column = None if error.offset is None else max(int(error.offset) - 1, 0)
        return ParseCheckResult(
            file_path=file_path,
            ok=False,
            error_message=error.msg,
            line=line,
            column=column,
        )
    return ParseCheckResult(file_path=file_path, ok=True)


def render_parse_check(result: ParseCheckResult, project_root: Path | None = None) -> str:
    label = _display_path(result.file_path, project_root)
    if result.ok:
        return f"{label} :: parse-check ok"
    return (
        f"{label} :: parse-check error "
        + f"line={result.line} column={result.column} message={result.error_message}"
    )


def render_parse_check_json(result: ParseCheckResult, project_root: Path | None = None) -> str:
    return json.dumps(
        {
            "column": result.column,
            "error_message": result.error_message,
            "file_path": _display_path(result.file_path, project_root),
            "line": result.line,
            "ok": result.ok,
        },
        indent=2,
        sort_keys=True,
    )


def render_error_json(error: CodeMapEditError, project_root: Path | None = None) -> str:
    return json.dumps(_error_payload(error, project_root), indent=2, sort_keys=True)


def build_class_diagram(target_path: Path, project_root: Path) -> ClassDiagramReport:
    resolved_target = target_path.resolve()
    python_files = _collect_python_files(resolved_target)
    module_reports = [_parse_module(file_path, project_root) for file_path in python_files]
    class_index = {
        class_info.qualified_name: class_info
        for module_report in module_reports
        for class_info in module_report.classes
    }
    relations: set[ClassRelation] = set()
    for module_report in module_reports:
        resolver = _NameResolver(module_report.module_name, module_report.imports, class_index)
        for class_info in module_report.classes:
            for raw_base in class_info.bases:
                resolved = resolver.resolve_reference(raw_base)
                if resolved is None or resolved == class_info.qualified_name:
                    continue
                relations.add(ClassRelation("inheritance", class_info.qualified_name, resolved))
            for field in class_info.fields:
                if field.annotation is None:
                    continue
                for candidate in _type_reference_names(field.annotation):
                    resolved = resolver.resolve_reference(candidate)
                    if resolved is None or resolved == class_info.qualified_name:
                        continue
                    relations.add(
                        ClassRelation(
                            "composition",
                            class_info.qualified_name,
                            resolved,
                            label=field.name,
                        )
                    )
    classes = tuple(sorted(class_index.values(), key=lambda item: (item.module_name, item.name, item.start_line)))
    sorted_relations = tuple(
        sorted(relations, key=lambda item: (item.kind, item.source, item.target, item.label or ""))
    )
    return ClassDiagramReport(target_path=resolved_target, classes=classes, relations=sorted_relations)


def render_class_diagram(target_path: Path, project_root: Path) -> str:
    report = build_class_diagram(target_path, project_root)
    grouped: dict[str, list[ClassInfo]] = {}
    for class_info in report.classes:
        grouped.setdefault(class_info.module_name, []).append(class_info)

    lines = [
        "@startuml",
        "hide empty members",
        "skinparam classAttributeIconSize 0",
    ]
    for module_name in sorted(grouped):
        lines.append(f'package "{module_name}" {{')
        for class_info in grouped[module_name]:
            alias = _alias_for_class(class_info.qualified_name)
            lines.append(f'  class "{class_info.name}" as {alias} {{')
            for field in class_info.fields:
                field_type = field.annotation or "Any"
                prefix = "~" if field.inferred else "+"
                lines.append(f"    {prefix}{field.name}: {field_type}")
            if class_info.fields and class_info.methods:
                lines.append("    --")
            for method in class_info.methods:
                method_prefix = "+" if method.kind == "method" else "+{static}"
                lines.append(f"    {method_prefix}{method.name}()")
            lines.append("  }")
        lines.append("}")
    for relation in report.relations:
        source_alias = _alias_for_class(relation.source)
        target_alias = _alias_for_class(relation.target)
        if relation.kind == "inheritance":
            lines.append(f"{source_alias} --|> {target_alias}")
            continue
        label = f" : {relation.label}" if relation.label else ""
        lines.append(f"{source_alias} *-- {target_alias}{label}")
    lines.append("@enduml")
    return "\n".join(lines) + "\n"


def build_facade_audit(
    file_path: Path,
    symbol: str,
    caller_roots: tuple[Path, ...],
    project_root: Path,
    *,
    include_private: bool = False,
) -> FacadeAuditReport:
    source = file_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(file_path))
    module_name = _module_name_for_file(file_path, project_root)
    imports = _import_aliases(tree, module_name)
    class_node = _find_class_node(tree, symbol, file_path)
    member_specs = [
        spec
        for spec in _class_surface_members(class_node, include_private=include_private, include_attributes=False)
        if spec.node is not None
    ]

    caller_files = _collect_caller_files(caller_roots)
    call_map = _collect_member_access_sites(
        caller_files,
        tuple(spec.name for spec in member_specs),
        project_root,
    )
    methods: list[FacadeMethodAudit] = []
    for member_spec in member_specs:
        assert member_spec.node is not None
        delegation = _member_delegation(member_spec, imports, module_name)
        call_sites = tuple(
            sorted(
                call_map.get(member_spec.name, ()),
                key=lambda item: (_display_path(item.file_path, project_root), item.line, item.column, item.access_kind),
            )
        )
        layer_counts = _sorted_layer_counts(call_sites)
        categories = _method_categories(call_sites, delegation)
        methods.append(
            FacadeMethodAudit(
                name=member_spec.name,
                start_line=member_spec.start_line,
                end_line=member_spec.end_line,
                visibility="private" if member_spec.name.startswith("_") else "public",
                categories=categories,
                layer_counts=layer_counts,
                delegation=delegation,
                call_sites=call_sites,
            )
        )
    return FacadeAuditReport(
        file_path=file_path,
        symbol=symbol,
        methods=tuple(methods),
        caller_roots=tuple(root.resolve() for root in caller_roots),
    )


def render_facade_audit(report: FacadeAuditReport, project_root: Path | None = None) -> str:
    label = _display_path(report.file_path, project_root)
    caller_roots = ", ".join(_display_path(root, project_root) for root in report.caller_roots)
    lines = [
        f"{label} :: {report.symbol}",
        f"caller_roots: {caller_roots}",
        f"methods: {len(report.methods)}",
    ]
    for method in report.methods:
        summary = [
            f"{method.start_line}-{method.end_line}",
            f"visibility={method.visibility}",
            f"callers={_render_layer_counts(method.layer_counts)}",
        ]
        if method.categories:
            summary.append("categories=" + ",".join(method.categories))
        if method.delegation is not None:
            target = method.delegation.target or method.delegation.expression
            summary.append(f"delegation={method.delegation.kind}")
            summary.append(f"target_group={method.delegation.target_group}")
            summary.append(f"target={target}")
        lines.append(f"- {method.name}: " + " ".join(summary))
        for call_site in method.call_sites:
            file_label = _display_path(call_site.file_path, project_root)
            caller_label = f" {call_site.enclosing_symbol}" if call_site.enclosing_symbol else ""
            lines.append(
                f"  {call_site.layer} {file_label}:{call_site.line} access={call_site.access_kind} "
                f"receiver={call_site.receiver}{caller_label}"
            )
    return "\n".join(lines)


def render_facade_audit_json(report: FacadeAuditReport, project_root: Path | None = None) -> str:
    payload = {
        "file_path": _display_path(report.file_path, project_root),
        "symbol": report.symbol,
        "caller_roots": [_display_path(root, project_root) for root in report.caller_roots],
        "methods": [
            {
                "name": method.name,
                "start_line": method.start_line,
                "end_line": method.end_line,
                "visibility": method.visibility,
                "categories": list(method.categories),
                "layer_counts": {layer: count for layer, count in method.layer_counts},
                "delegation": (
                    None
                    if method.delegation is None
                    else {
                        "kind": method.delegation.kind,
                        "expression": method.delegation.expression,
                        "target": method.delegation.target,
                        "target_group": method.delegation.target_group,
                    }
                ),
                "call_sites": [
                    {
                        "file_path": _display_path(call_site.file_path, project_root),
                        "line": call_site.line,
                        "column": call_site.column,
                        "receiver": call_site.receiver,
                        "enclosing_symbol": call_site.enclosing_symbol,
                        "layer": call_site.layer,
                        "access_kind": call_site.access_kind,
                    }
                    for call_site in method.call_sites
                ],
            }
            for method in report.methods
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def build_protocol_audit(
    target_path: Path,
    project_root: Path,
    *,
    symbol: str | None = None,
    include_private: bool = False,
    facade_file_path: Path | None = None,
    facade_symbol: str | None = "GameSession",
) -> ProtocolAuditReport:
    resolved_target = target_path.resolve()
    contracts = _collect_feature_protocol_contracts(project_root)
    contracts_by_qualified = {contract.qualified_name: contract for contract in contracts}
    contracts_by_member: dict[str, list[ProtocolContract]] = defaultdict(list)
    for contract in contracts:
        for member_name in contract.members:
            contracts_by_member[member_name].append(contract)

    resolved_facade_path = _default_facade_file(project_root) if facade_file_path is None else facade_file_path.resolve()
    facade_members: set[str] = set()
    if resolved_facade_path is not None and facade_symbol:
        try:
            facade_members = _class_surface_member_names(
                resolved_facade_path,
                facade_symbol,
                project_root,
                include_private=include_private,
            )
        except ValueError:
            facade_members = set()

    classes: list[ProtocolTypeAudit] = []
    for file_path in _collect_python_files(resolved_target):
        source = file_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(file_path))
        module_name = _module_name_for_file(file_path, project_root)
        imports = _import_aliases(tree, module_name)
        for statement in tree.body:
            if not isinstance(statement, ast.ClassDef):
                continue
            if symbol is not None and statement.name != symbol:
                continue
            resolved_bases = _resolved_class_bases(statement, imports, module_name)
            is_protocol = _is_protocol_class(statement, resolved_bases)
            member_specs = _class_surface_members(
                statement,
                include_private=include_private,
                include_attributes=is_protocol,
            )
            base_contracts = tuple(
                sorted(
                    contract.qualified_name
                    for base_name in resolved_bases
                    for contract in [contracts_by_qualified.get(base_name)]
                    if contract is not None
                )
            )
            owner_features = {
                contract.feature
                for base_name in resolved_bases
                for contract in [contracts_by_qualified.get(base_name)]
                if contract is not None
            }
            member_audits: list[ProtocolMemberAudit] = []
            for member_spec in member_specs:
                replacement_contracts = tuple(
                    sorted(
                        contract.qualified_name
                        for contract in contracts_by_member.get(member_spec.name, ())
                    )
                )
                member_owner_features = tuple(
                    sorted(
                        {
                            contract.feature
                            for contract in contracts_by_member.get(member_spec.name, ())
                        }
                    )
                )
                owner_features.update(member_owner_features)
                delegation = _member_delegation(member_spec, imports, module_name)
                categories: list[str] = []
                if member_spec.name in facade_members:
                    categories.append("session_mirror")
                if replacement_contracts:
                    categories.append("replaceable_with_feature_contract")
                if delegation is not None:
                    categories.append("wrapper")
                    if delegation.target_group not in {"self", "unresolved"}:
                        categories.append(f"wrapper_to_{delegation.target_group}")
                if len(member_owner_features) > 1:
                    categories.append("mixed_member_owners")
                member_audits.append(
                    ProtocolMemberAudit(
                        name=member_spec.name,
                        kind=member_spec.kind,
                        start_line=member_spec.start_line,
                        end_line=member_spec.end_line,
                        categories=tuple(categories),
                        owner_features=member_owner_features,
                        replacement_contracts=replacement_contracts,
                        delegation=delegation,
                    )
                )
            class_categories: list[str] = []
            if is_protocol:
                class_categories.append("protocol")
            if base_contracts:
                class_categories.append("feature_protocol_surface")
            if any("session_mirror" in member.categories for member in member_audits):
                class_categories.append("session_mirror")
            if any(member.delegation is not None for member in member_audits):
                class_categories.append("delegating_surface")
            if len(owner_features) > 1:
                class_categories.append("mixed_feature_owners")
            if not _is_protocol_surface_class(
                statement.name,
                is_protocol,
                base_contracts,
                member_audits,
                class_categories,
            ):
                continue
            classes.append(
                ProtocolTypeAudit(
                    file_path=file_path,
                    name=statement.name,
                    qualified_name=f"{module_name}.{statement.name}",
                    kind="protocol" if is_protocol else "class",
                    start_line=statement.lineno,
                    end_line=_end_line(statement),
                    bases=resolved_bases,
                    base_contracts=base_contracts,
                    owner_features=tuple(sorted(owner_features)),
                    categories=tuple(class_categories),
                    members=tuple(member_audits),
                )
            )
    classes.sort(key=lambda item: (_display_path(item.file_path, project_root), item.start_line, item.name))
    return ProtocolAuditReport(
        target_path=resolved_target,
        file_path=resolved_target if resolved_target.is_file() else None,
        symbol=symbol,
        facade_file_path=resolved_facade_path,
        facade_symbol=facade_symbol,
        classes=tuple(classes),
    )


def render_protocol_audit(report: ProtocolAuditReport, project_root: Path | None = None) -> str:
    label = _display_path(report.target_path, project_root)
    lines = [
        f"{label} :: protocol-audit",
        f"classes: {len(report.classes)}",
    ]
    if report.facade_file_path is not None and report.facade_symbol is not None:
        lines.append(
            "facade: "
            + f"{_display_path(report.facade_file_path, project_root)} :: {report.facade_symbol}"
        )
    for class_audit in report.classes:
        summary = [
            f"{class_audit.start_line}-{class_audit.end_line}",
            f"kind={class_audit.kind}",
        ]
        if class_audit.owner_features:
            summary.append("owners=" + ",".join(class_audit.owner_features))
        if class_audit.categories:
            summary.append("categories=" + ",".join(class_audit.categories))
        if class_audit.base_contracts:
            summary.append("base_contracts=" + ",".join(class_audit.base_contracts))
        lines.append(
            f"- {_display_path(class_audit.file_path, project_root)} :: {class_audit.name}: " + " ".join(summary)
        )
        for member in class_audit.members:
            member_summary = [
                f"{member.start_line}-{member.end_line}",
                f"kind={member.kind}",
            ]
            if member.owner_features:
                member_summary.append("owners=" + ",".join(member.owner_features))
            if member.categories:
                member_summary.append("categories=" + ",".join(member.categories))
            if member.replacement_contracts:
                member_summary.append("replaceable_with=" + ",".join(member.replacement_contracts))
            if member.delegation is not None:
                target = member.delegation.target or member.delegation.expression
                member_summary.append(f"delegation={member.delegation.kind}")
                member_summary.append(f"target_group={member.delegation.target_group}")
                member_summary.append(f"target={target}")
            lines.append(f"  - {member.name}: " + " ".join(member_summary))
    return "\n".join(lines)


def render_protocol_audit_json(report: ProtocolAuditReport, project_root: Path | None = None) -> str:
    payload = {
        "target_path": _display_path(report.target_path, project_root),
        "file_path": None if report.file_path is None else _display_path(report.file_path, project_root),
        "symbol": report.symbol,
        "facade_file_path": (
            None
            if report.facade_file_path is None
            else _display_path(report.facade_file_path, project_root)
        ),
        "facade_symbol": report.facade_symbol,
        "classes": [
            {
                "file_path": _display_path(class_audit.file_path, project_root),
                "name": class_audit.name,
                "qualified_name": class_audit.qualified_name,
                "kind": class_audit.kind,
                "start_line": class_audit.start_line,
                "end_line": class_audit.end_line,
                "bases": list(class_audit.bases),
                "base_contracts": list(class_audit.base_contracts),
                "owner_features": list(class_audit.owner_features),
                "categories": list(class_audit.categories),
                "members": [
                    {
                        "name": member.name,
                        "kind": member.kind,
                        "start_line": member.start_line,
                        "end_line": member.end_line,
                        "owner_features": list(member.owner_features),
                        "categories": list(member.categories),
                        "replacement_contracts": list(member.replacement_contracts),
                        "delegation": (
                            None
                            if member.delegation is None
                            else {
                                "kind": member.delegation.kind,
                                "expression": member.delegation.expression,
                                "target": member.delegation.target,
                                "target_group": member.delegation.target_group,
                            }
                        ),
                    }
                    for member in class_audit.members
                ],
            }
            for class_audit in report.classes
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def compact_help() -> str:
    return "\n".join(
        [
            "code_map.py help",
            "code_map.py map <python_file> [--json]",
            "code_map.py class-diagram <path> [output.puml]",
            "code_map.py facade-audit <python_file> --symbol <ClassName> --callers <path> [<path> ...] [--json]",
            "code_map.py protocol-audit <path> [--symbol <ClassName>] [--json]",
            "code_map.py symbol-get <python_file> --symbol <name> [--json]",
            "code_map.py replace-symbol <python_file> --symbol <name> --expect-hash <sha256> (--replacement-env <VAR> | --replacement-file <path> | --replacement-text <text> | --replacement-stdin) [--check-only] [--json]",
            "code_map.py replace-symbol-body <python_file> --symbol <name> --expect-hash <sha256> (--replacement-env <VAR> | --replacement-file <path> | --replacement-text <text> | --replacement-stdin) [--check-only] [--json]",
            "code_map.py insert-before-symbol <python_file> --symbol <name> --expect-hash <sha256> (--snippet-env <VAR> | --snippet-file <path> | --snippet-text <text> | --snippet-stdin) [--check-only] [--json]",
            "code_map.py insert-after-symbol <python_file> --symbol <name> --expect-hash <sha256> (--snippet-env <VAR> | --snippet-file <path> | --snippet-text <text> | --snippet-stdin) [--check-only] [--json]",
            "code_map.py batch (--plan-env <VAR> | --plan-file <path> | --plan-text <json> | --plan-stdin) [--check-only] [--json]",
            "code_map.py imports-add <python_file> --import <statement> [--check-only] [--json]",
            "code_map.py parse-check <python_file> [--json]",
        ]
    )


@dataclass(frozen=True)
class _ModuleReport:
    module_name: str
    file_path: Path
    classes: tuple[ClassInfo, ...]
    imports: dict[str, str]


class _NameResolver:
    def __init__(self, module_name: str, imports: dict[str, str], class_index: dict[str, ClassInfo]) -> None:
        self._module_name = module_name
        self._imports = imports
        self._class_index = class_index

    def resolve_reference(self, reference: str) -> str | None:
        normalized = reference.strip("'\" ")
        if not normalized:
            return None
        if normalized in self._class_index:
            return normalized
        if normalized in self._imports:
            candidate = self._imports[normalized]
            if candidate in self._class_index:
                return candidate
        module_local = f"{self._module_name}.{normalized}"
        if module_local in self._class_index:
            return module_local
        package_prefix, _, _module_leaf = self._module_name.rpartition(".")
        if package_prefix:
            package_local = f"{package_prefix}.{normalized}"
            if package_local in self._class_index:
                return package_local
        return None


class _MemberAccessVisitor(ast.NodeVisitor):
    def __init__(self, target_members: tuple[str, ...], file_path: Path, project_root: Path) -> None:
        self._target_members = set(target_members)
        self._file_path = file_path
        self._project_root = project_root
        self._symbol_stack: list[str] = []
        self.call_sites: dict[str, list[FacadeCallSite]] = defaultdict(list)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._symbol_stack.append(node.name)
        self.generic_visit(node)
        self._symbol_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._symbol_stack.append(node.name)
        self.generic_visit(node)
        self._symbol_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._symbol_stack.append(node.name)
        self.generic_visit(node)
        self._symbol_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and node.func.attr in self._target_members:
            self._record(node.func, access_kind="call")
            self.visit(node.func.value)
        else:
            self.visit(node.func)
        for argument in node.args:
            self.visit(argument)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Load) and node.attr in self._target_members:
            self._record(node, access_kind="attribute")
        self.visit(node.value)

    def _record(self, node: ast.Attribute, *, access_kind: str) -> None:
        receiver = _render_expr(node.value) or "<unknown>"
        self.call_sites[node.attr].append(
            FacadeCallSite(
                file_path=self._file_path,
                line=node.lineno,
                column=node.col_offset,
                receiver=receiver,
                enclosing_symbol=".".join(self._symbol_stack) if self._symbol_stack else None,
                layer=_layer_name(self._file_path, self._project_root),
                access_kind=access_kind,
            )
        )


def _build_nodes(body: list[ast.stmt], parents: tuple[str, ...] = ()) -> list[CodeMapNode]:
    nodes: list[CodeMapNode] = []
    for statement in body:
        if isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            local_qualified_name = ".".join((*parents, statement.name)) if parents else statement.name
            kind = _statement_kind(statement)
            nodes.append(
                CodeMapNode(
                    kind=kind,
                    name=statement.name,
                    qualified_name=local_qualified_name,
                    start_line=statement.lineno,
                    end_line=_end_line(statement),
                    children=tuple(_build_nodes(statement.body, (*parents, statement.name))),
                )
            )
    return nodes


def _collect_symbol_specs(
    body: list[ast.stmt],
    module_name: str,
    source: str,
    line_offsets: list[int],
    parents: tuple[str, ...] = (),
) -> list[_SymbolSpec]:
    specs: list[_SymbolSpec] = []
    for statement in body:
        if not isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        local_qualified_name = ".".join((*parents, statement.name)) if parents else statement.name
        qualified_name = f"{module_name}.{local_qualified_name}" if module_name else local_qualified_name
        node_span = _span_for_node(statement, line_offsets)
        body_span = _body_span_for_node(statement, line_offsets)
        specs.append(
            _SymbolSpec(
                kind=_statement_kind(statement),
                name=statement.name,
                qualified_name=qualified_name,
                local_qualified_name=local_qualified_name,
                node_span=node_span,
                node_indent_text=_line_prefix(source, node_span.start_line, node_span.start_column),
                body_span=body_span,
                body_indent_text=(
                    None if body_span is None else _line_prefix(source, body_span.start_line, body_span.start_column)
                ),
            )
        )
        specs.extend(
            _collect_symbol_specs(
                statement.body,
                module_name,
                source,
                line_offsets,
                (*parents, statement.name),
            )
        )
    return specs


def _resolve_symbol_spec(specs: list[_SymbolSpec], module_name: str, symbol: str) -> _SymbolSpec:
    exact_matches = [spec for spec in specs if spec.qualified_name == symbol]
    if len(exact_matches) == 1:
        return exact_matches[0]
    local_matches = [spec for spec in specs if spec.local_qualified_name == symbol]
    if len(local_matches) == 1:
        return local_matches[0]
    if len(local_matches) > 1:
        candidates = ", ".join(sorted(spec.qualified_name for spec in local_matches))
        raise ValueError(f"ambiguous symbol '{symbol}': {candidates}")
    if "." not in symbol:
        name_matches = [spec for spec in specs if spec.name == symbol]
        if len(name_matches) == 1:
            return name_matches[0]
        if len(name_matches) > 1:
            candidates = ", ".join(sorted(spec.qualified_name for spec in name_matches))
            raise ValueError(f"ambiguous symbol '{symbol}': {candidates}")
    raise ValueError(f"symbol not found in module '{module_name}': {symbol}")


def _snapshot_from_spec(
    file_path: Path,
    module_name: str,
    source: str,
    spec: _SymbolSpec,
) -> SymbolSnapshot:
    node_source = source[spec.node_span.start_offset : spec.node_span.end_offset]
    body_source = (
        None
        if spec.body_span is None
        else source[spec.body_span.start_offset : spec.body_span.end_offset]
    )
    body_start_line = None if spec.body_span is None else spec.body_span.start_line
    body_end_line = None if spec.body_span is None else spec.body_span.end_line
    body_indent_columns = None if spec.body_span is None else spec.body_span.start_column
    return SymbolSnapshot(
        file_path=file_path,
        module_name=module_name,
        kind=spec.kind,
        name=spec.name,
        qualified_name=spec.qualified_name,
        local_qualified_name=spec.local_qualified_name,
        start_line=spec.node_span.start_line,
        end_line=spec.node_span.end_line,
        shape_hash=_shape_hash_for_source(spec.kind, spec.name, node_source),
        node_hash=_hash_text(node_source),
        node_source=node_source,
        body_hash=None if body_source is None else _hash_text(body_source),
        body_source=body_source,
        body_start_line=body_start_line,
        body_end_line=body_end_line,
        body_indent_columns=body_indent_columns,
    )


def _build_symbol_snapshot_from_source(
    file_path: Path,
    project_root: Path,
    symbol: str,
    source: str,
) -> SymbolSnapshot:
    tree = ast.parse(source, filename=str(file_path))
    module_name = _module_name_for_file(file_path, project_root)
    line_offsets = _line_start_offsets(source)
    spec = _resolve_symbol_spec(
        _collect_symbol_specs(tree.body, module_name, source, line_offsets),
        module_name,
        symbol,
    )
    return _snapshot_from_spec(file_path, module_name, source, spec)


def _apply_symbol_edit_to_source(
    file_path: Path,
    project_root: Path,
    source: str,
    symbol: str,
    expected_hash: str,
    replacement_text: str,
    *,
    operation: str,
    scope: str,
    check_only: bool,
) -> tuple[EditResult, str]:
    tree = ast.parse(source, filename=str(file_path))
    module_name = _module_name_for_file(file_path, project_root)
    line_offsets = _line_start_offsets(source)
    spec = _resolve_symbol_spec(
        _collect_symbol_specs(tree.body, module_name, source, line_offsets),
        module_name,
        symbol,
    )
    snapshot = _snapshot_from_spec(file_path, module_name, source, spec)
    span = spec.node_span if scope == "node" else spec.body_span
    indent_text = spec.node_indent_text if scope == "node" else spec.body_indent_text
    current_hash = snapshot.node_hash if scope == "node" else snapshot.body_hash
    if span is None or indent_text is None or current_hash is None:
        raise CodeMapEditError(
            CodeMapErrorDetails(
                code="missing-edit-span",
                message=f"symbol has no replaceable {scope}: {snapshot.local_qualified_name}",
                file_path=file_path,
                symbol=snapshot.local_qualified_name,
                current_snapshot=snapshot,
            )
        )
    if current_hash != expected_hash:
        raise CodeMapEditError(
            CodeMapErrorDetails(
                code="hash-mismatch",
                message=(
                    f"symbol {scope} hash mismatch: expected={expected_hash} "
                    + f"actual={current_hash} symbol={snapshot.local_qualified_name}"
                ),
                file_path=file_path,
                symbol=snapshot.local_qualified_name,
                expected_hash=expected_hash,
                actual_hash=current_hash,
                current_snapshot=snapshot,
            )
        )
    rendered = _render_replacement_at_offset(replacement_text, indent_text)
    new_source = source[: span.start_offset] + rendered + source[span.end_offset :]
    _validate_source_or_raise(new_source, file_path, symbol=snapshot.local_qualified_name)
    new_snapshot = _build_symbol_snapshot_from_source(file_path, project_root, symbol, new_source)
    new_hash = new_snapshot.node_hash if scope == "node" else new_snapshot.body_hash
    if new_hash is None:
        raise CodeMapEditError(
            CodeMapErrorDetails(
                code="missing-edit-span",
                message=f"symbol has no replaceable {scope} after edit: {new_snapshot.local_qualified_name}",
                file_path=file_path,
                symbol=new_snapshot.local_qualified_name,
                current_snapshot=new_snapshot,
            )
        )
    return (
        EditResult(
            file_path=file_path,
            operation=operation,
            target=new_snapshot.local_qualified_name,
            changed=True,
            check_only=check_only,
            old_hash=current_hash,
            new_hash=new_hash,
            snapshot=new_snapshot,
            diff=_render_unified_diff(source, new_source, file_path),
        ),
        new_source,
    )


def _insert_relative_to_symbol_in_source(
    file_path: Path,
    project_root: Path,
    source: str,
    symbol: str,
    expected_hash: str,
    snippet_text: str,
    *,
    position: str,
    check_only: bool,
) -> tuple[EditResult, str]:
    tree = ast.parse(source, filename=str(file_path))
    module_name = _module_name_for_file(file_path, project_root)
    line_offsets = _line_start_offsets(source)
    spec = _resolve_symbol_spec(
        _collect_symbol_specs(tree.body, module_name, source, line_offsets),
        module_name,
        symbol,
    )
    snapshot = _snapshot_from_spec(file_path, module_name, source, spec)
    if snapshot.node_hash != expected_hash:
        raise CodeMapEditError(
            CodeMapErrorDetails(
                code="hash-mismatch",
                message=(
                    "anchor symbol hash mismatch: "
                    + f"expected={expected_hash} actual={snapshot.node_hash} symbol={snapshot.local_qualified_name}"
                ),
                file_path=file_path,
                symbol=snapshot.local_qualified_name,
                expected_hash=expected_hash,
                actual_hash=snapshot.node_hash,
                current_snapshot=snapshot,
            )
        )
    if position == "before":
        insert_offset = line_offsets[spec.node_span.start_line - 1]
        insert_line = spec.node_span.start_line
    else:
        insert_offset = spec.node_span.end_offset
        if source[insert_offset: insert_offset + 1] == "\n":
            insert_offset += 1
        insert_line = spec.node_span.end_line + 1
    rendered = _render_indented_block(snippet_text, spec.node_indent_text, ensure_trailing_newline=True)
    new_source = source[:insert_offset] + rendered + source[insert_offset:]
    _validate_source_or_raise(new_source, file_path, symbol=snapshot.local_qualified_name)
    return (
        EditResult(
            file_path=file_path,
            operation=f"insert-{position}-symbol",
            target=snapshot.local_qualified_name,
            changed=True,
            check_only=check_only,
            old_hash=snapshot.node_hash,
            new_hash=snapshot.node_hash,
            snapshot=snapshot,
            insert_line=insert_line,
            diff=_render_unified_diff(source, new_source, file_path),
        ),
        new_source,
    )


def _add_import_statement_to_source(
    file_path: Path,
    source: str,
    statement: str,
    *,
    check_only: bool,
) -> tuple[EditResult, str]:
    tree = ast.parse(source, filename=str(file_path))
    import_node = _parse_import_statement(statement)
    normalized = _normalized_import_statement(import_node)
    for existing in tree.body:
        if isinstance(existing, (ast.Import, ast.ImportFrom)):
            if _normalized_import_statement(existing) == normalized:
                return (
                    EditResult(
                        file_path=file_path,
                        operation="imports-add",
                        target=statement.strip(),
                        changed=False,
                        check_only=check_only,
                        statement=statement.strip(),
                    ),
                    source,
                )
    line_offsets = _line_start_offsets(source)
    insert_offset, insert_line = _import_insert_position(tree, source, line_offsets)
    rendered = _render_indented_block(statement, indent_text="", ensure_trailing_newline=True)
    new_source = source[:insert_offset] + rendered + source[insert_offset:]
    _validate_source_or_raise(new_source, file_path)
    return (
        EditResult(
            file_path=file_path,
            operation="imports-add",
            target=statement.strip(),
            changed=True,
            check_only=check_only,
            insert_line=insert_line,
            statement=statement.strip(),
            diff=_render_unified_diff(source, new_source, file_path),
        ),
        new_source,
    )


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
    normalized_operations: list[dict[str, object]] = []
    for index, operation in enumerate(operations):
        if not isinstance(operation, dict):
            raise ValueError(f"batch operation #{index + 1} must be an object")
        normalized_operations.append(operation)
    return {
        "check_only": bool(check_only),
        "operations": normalized_operations,
    }


def _resolve_batch_file_path(operation: dict[str, object], project_root: Path, *, operation_index: int) -> Path:
    file_path = operation.get("file_path")
    if not isinstance(file_path, str) or not file_path.strip():
        raise ValueError(f"batch operation #{operation_index + 1} requires non-empty 'file_path'")
    path = Path(file_path)
    if not path.is_absolute():
        path = (project_root / path).resolve()
    return path


def _apply_batch_operation(
    operation: dict[str, object],
    project_root: Path,
    staged_sources: dict[Path, tuple[str, str]],
    *,
    check_only: bool,
    operation_index: int,
) -> tuple[EditResult, str, str]:
    command = operation.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"batch operation #{operation_index + 1} requires non-empty 'command'")
    file_path = _resolve_batch_file_path(operation, project_root, operation_index=operation_index)
    source, encoding = staged_sources.get(file_path, _read_source_with_encoding(file_path))
    if command == "replace-symbol":
        return (
            *_apply_symbol_edit_to_source(
                file_path,
                project_root,
                source,
                _required_batch_string(operation, "symbol", operation_index),
                _required_batch_string(operation, "expect_hash", operation_index),
                _required_batch_string(operation, "replacement_text", operation_index),
                operation=command,
                scope="node",
                check_only=check_only,
            ),
            encoding,
        )
    if command == "replace-symbol-body":
        return (
            *_apply_symbol_edit_to_source(
                file_path,
                project_root,
                source,
                _required_batch_string(operation, "symbol", operation_index),
                _required_batch_string(operation, "expect_hash", operation_index),
                _required_batch_string(operation, "replacement_text", operation_index),
                operation=command,
                scope="body",
                check_only=check_only,
            ),
            encoding,
        )
    if command == "insert-before-symbol":
        return (
            *_insert_relative_to_symbol_in_source(
                file_path,
                project_root,
                source,
                _required_batch_string(operation, "symbol", operation_index),
                _required_batch_string(operation, "expect_hash", operation_index),
                _required_batch_string(operation, "snippet_text", operation_index),
                position="before",
                check_only=check_only,
            ),
            encoding,
        )
    if command == "insert-after-symbol":
        return (
            *_insert_relative_to_symbol_in_source(
                file_path,
                project_root,
                source,
                _required_batch_string(operation, "symbol", operation_index),
                _required_batch_string(operation, "expect_hash", operation_index),
                _required_batch_string(operation, "snippet_text", operation_index),
                position="after",
                check_only=check_only,
            ),
            encoding,
        )
    if command == "imports-add":
        return (
            *_add_import_statement_to_source(
                file_path,
                source,
                _required_batch_string(operation, "import_statement", operation_index),
                check_only=check_only,
            ),
            encoding,
        )
    raise ValueError(f"unsupported batch command in operation #{operation_index + 1}: {command}")


def _required_batch_string(operation: dict[str, object], field_name: str, operation_index: int) -> str:
    value = operation.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"batch operation #{operation_index + 1} requires non-empty '{field_name}'")
    return value


def _render_unified_diff(old_source: str, new_source: str, file_path: Path) -> str | None:
    if old_source == new_source:
        return None
    diff_lines = list(
        difflib.unified_diff(
            old_source.splitlines(),
            new_source.splitlines(),
            fromfile=f"{file_path} (before)",
            tofile=f"{file_path} (after)",
            lineterm="",
        )
    )
    return None if not diff_lines else "\n".join(diff_lines)


def _validate_source_or_raise(new_source: str, file_path: Path, *, symbol: str | None = None) -> None:
    try:
        ast.parse(new_source, filename=str(file_path))
    except SyntaxError as error:
        line = None if error.lineno is None else int(error.lineno)
        column = None if error.offset is None else max(int(error.offset) - 1, 0)
        raise CodeMapEditError(
            CodeMapErrorDetails(
                code="syntax-error",
                message=(
                    "replacement produced invalid syntax"
                    + ("" if line is None else f" at {line}:{column}")
                    + f": {error.msg}"
                ),
                file_path=file_path,
                symbol=symbol,
                line=line,
                column=column,
            )
        ) from error


def _atomic_write_text(file_path: Path, text: str, encoding: str) -> None:
    temp_path = file_path.with_name(f"{file_path.name}.{uuid4().hex}.tmp")
    try:
        temp_path.write_text(text, encoding=encoding)
        os.replace(temp_path, file_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _parse_import_statement(statement: str) -> ast.Import | ast.ImportFrom:
    normalized = statement.strip()
    if not normalized:
        raise CodeMapEditError(CodeMapErrorDetails(code="invalid-import", message="import statement is empty"))
    try:
        tree = ast.parse(normalized, mode="exec")
    except SyntaxError as error:
        line = None if error.lineno is None else int(error.lineno)
        column = None if error.offset is None else max(int(error.offset) - 1, 0)
        raise CodeMapEditError(
            CodeMapErrorDetails(
                code="invalid-import",
                message=f"invalid import statement: {error.msg}",
                line=line,
                column=column,
            )
        ) from error
    if len(tree.body) != 1 or not isinstance(tree.body[0], (ast.Import, ast.ImportFrom)):
        raise CodeMapEditError(
            CodeMapErrorDetails(
                code="invalid-import",
                message="statement must contain exactly one import or from-import",
            )
        )
    return tree.body[0]


def _normalized_import_statement(node: ast.Import | ast.ImportFrom) -> str:
    return ast.dump(node, annotate_fields=True, include_attributes=False)


def _import_insert_position(tree: ast.Module, source: str, line_offsets: list[int]) -> tuple[int, int]:
    if not tree.body:
        return 0, 1
    insert_after_line = 0
    body = tree.body
    body_index = 0
    if _module_docstring_node(body) is not None:
        docstring_node = body[0]
        insert_after_line = _end_line(docstring_node)
        body_index = 1
    while body_index < len(body):
        statement = body[body_index]
        if isinstance(statement, ast.ImportFrom) and statement.module == "__future__":
            insert_after_line = _end_line(statement)
            body_index += 1
            continue
        break
    while body_index < len(body):
        statement = body[body_index]
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            insert_after_line = _end_line(statement)
            body_index += 1
            continue
        break
    if insert_after_line == 0:
        return 0, 1
    insert_offset = line_offsets[insert_after_line]
    return insert_offset, insert_after_line + 1


def _module_docstring_node(body: list[ast.stmt]) -> ast.stmt | None:
    if not body:
        return None
    first = body[0]
    if not isinstance(first, ast.Expr) or not isinstance(first.value, ast.Constant):
        return None
    if not isinstance(first.value.value, str):
        return None
    return first


def _parse_module(file_path: Path, project_root: Path) -> _ModuleReport:
    source = file_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(file_path))
    module_name = _module_name_for_file(file_path, project_root)
    imports = _import_aliases(tree, module_name)
    classes: list[ClassInfo] = []
    for statement in tree.body:
        if not isinstance(statement, ast.ClassDef):
            continue
        qualified_name = f"{module_name}.{statement.name}"
        methods = tuple(_class_methods(statement))
        fields = tuple(_class_fields(statement))
        bases = tuple(sorted({_render_expr(base) for base in statement.bases if _render_expr(base)}))
        classes.append(
            ClassInfo(
                module_name=module_name,
                qualified_name=qualified_name,
                file_path=file_path,
                name=statement.name,
                start_line=statement.lineno,
                end_line=_end_line(statement),
                bases=bases,
                fields=fields,
                methods=methods,
            )
        )
    return _ModuleReport(
        module_name=module_name,
        file_path=file_path,
        classes=tuple(classes),
        imports=imports,
    )


def _class_methods(class_node: ast.ClassDef) -> list[ClassMethod]:
    methods: list[ClassMethod] = []
    for statement in class_node.body:
        if isinstance(statement, ast.FunctionDef):
            methods.append(
                ClassMethod(
                    name=statement.name,
                    kind="method" if _is_instance_method(statement) else "callable",
                    start_line=statement.lineno,
                    end_line=_end_line(statement),
                )
            )
        elif isinstance(statement, ast.AsyncFunctionDef):
            methods.append(
                ClassMethod(
                    name=statement.name,
                    kind="async method" if _is_instance_method(statement) else "async callable",
                    start_line=statement.lineno,
                    end_line=_end_line(statement),
                )
            )
    return methods


def _class_fields(class_node: ast.ClassDef) -> list[ClassField]:
    fields: dict[str, ClassField] = {}
    for statement in class_node.body:
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            annotation = _render_expr(statement.annotation)
            fields[statement.target.id] = ClassField(
                name=statement.target.id,
                annotation=annotation,
                start_line=statement.lineno,
                inferred=False,
            )
            continue
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(statement):
            if isinstance(inner, ast.AnnAssign) and _is_self_attribute(inner.target):
                field_name = inner.target.attr
                annotation = _render_expr(inner.annotation)
                fields.setdefault(
                    field_name,
                    ClassField(
                        name=field_name,
                        annotation=annotation,
                        start_line=inner.lineno,
                        inferred=False,
                    ),
                )
                continue
            if isinstance(inner, ast.Assign):
                inferred = _infer_self_assignment(inner)
                if inferred is None:
                    continue
                field_name, annotation = inferred
                fields.setdefault(
                    field_name,
                    ClassField(
                        name=field_name,
                        annotation=annotation,
                        start_line=inner.lineno,
                        inferred=True,
                    ),
                )
    return sorted(fields.values(), key=lambda item: (item.start_line, item.name))


def _find_class_node(tree: ast.Module, symbol: str, file_path: Path) -> ast.ClassDef:
    for statement in tree.body:
        if isinstance(statement, ast.ClassDef) and statement.name == symbol:
            return statement
    raise ValueError(f'class "{symbol}" not found in {file_path}')


def _collect_caller_files(caller_roots: tuple[Path, ...]) -> list[Path]:
    files: set[Path] = set()
    for root in caller_roots:
        resolved_root = root.resolve()
        for file_path in _collect_python_files(resolved_root):
            files.add(file_path.resolve())
    return sorted(files)


def _collect_member_access_sites(
    caller_files: list[Path],
    member_names: tuple[str, ...],
    project_root: Path,
) -> dict[str, tuple[FacadeCallSite, ...]]:
    collected: dict[str, list[FacadeCallSite]] = defaultdict(list)
    for file_path in caller_files:
        source = file_path.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(file_path))
        visitor = _MemberAccessVisitor(member_names, file_path, project_root)
        visitor.visit(tree)
        for member_name, call_sites in visitor.call_sites.items():
            collected[member_name].extend(call_sites)
    return {
        member_name: tuple(
            sorted(
                call_sites,
                key=lambda item: (
                    _display_path(item.file_path, project_root),
                    item.line,
                    item.column,
                    item.access_kind,
                ),
            )
        )
        for member_name, call_sites in collected.items()
    }


def _member_delegation(
    member_spec: _SurfaceMemberSpec,
    imports: dict[str, str],
    module_name: str,
) -> FacadeDelegation | None:
    if not isinstance(member_spec.node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return None
    return _method_delegation(member_spec.node, imports, module_name)


def _method_delegation(
    method_node: ast.FunctionDef | ast.AsyncFunctionDef,
    imports: dict[str, str],
    module_name: str,
) -> FacadeDelegation | None:
    body = list(method_node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
        body = body[1:]
    if len(body) != 1:
        return None
    statement = body[0]
    expression: ast.AST | None = None
    if isinstance(statement, ast.Return) and statement.value is not None:
        expression = statement.value
    elif isinstance(statement, ast.Expr):
        expression = statement.value
    if expression is None:
        return None
    return _delegation_for_expression(expression, imports, module_name)


def _delegation_for_expression(
    expression: ast.AST,
    imports: dict[str, str],
    module_name: str,
) -> FacadeDelegation | None:
    expression_text = _render_expr(expression)
    if not expression_text:
        return None
    if isinstance(expression, ast.Call):
        return _delegation_for_call(expression, expression_text, imports, module_name)
    if isinstance(expression, ast.Attribute):
        target = _resolve_reference(expression, imports, module_name)
        return FacadeDelegation(
            kind="attribute_read",
            expression=expression_text,
            target=target,
            target_group=_reference_group(target, module_name),
        )
    return None


def _delegation_for_call(
    expression: ast.Call,
    expression_text: str,
    imports: dict[str, str],
    module_name: str,
) -> FacadeDelegation | None:
    if isinstance(expression.func, ast.Attribute):
        receiver = expression.func.value
        kind = "attribute_call"
        target: str | None = None
        if isinstance(receiver, ast.Call):
            kind = "helper_call"
            helper_target = _resolve_reference(receiver.func, imports, module_name)
            target = f"{helper_target}.{expression.func.attr}" if helper_target else None
        elif _is_self_expression(receiver):
            kind = "self_call"
            receiver_target = _render_expr(receiver)
            target = f"{receiver_target}.{expression.func.attr}" if receiver_target else None
        else:
            receiver_target = _resolve_reference(receiver, imports, module_name)
            target = f"{receiver_target}.{expression.func.attr}" if receiver_target else None
        return FacadeDelegation(
            kind=kind,
            expression=expression_text,
            target=target,
            target_group=_reference_group(target, module_name),
        )
    if isinstance(expression.func, ast.Name):
        target = _resolve_reference(expression.func, imports, module_name)
        return FacadeDelegation(
            kind="function_call",
            expression=expression_text,
            target=target,
            target_group=_reference_group(target, module_name),
        )
    return None


def _class_surface_members(
    class_node: ast.ClassDef,
    *,
    include_private: bool,
    include_attributes: bool,
) -> list[_SurfaceMemberSpec]:
    members: list[_SurfaceMemberSpec] = []
    for statement in class_node.body:
        if isinstance(statement, ast.AnnAssign) and include_attributes and isinstance(statement.target, ast.Name):
            if include_private or not statement.target.id.startswith("_"):
                members.append(
                    _SurfaceMemberSpec(
                        name=statement.target.id,
                        kind="attribute",
                        start_line=statement.lineno,
                        end_line=_end_line(statement),
                        node=None,
                    )
                )
            continue
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not include_private and statement.name.startswith("_"):
            continue
        if _is_property(statement):
            kind = "property"
        elif isinstance(statement, ast.AsyncFunctionDef):
            kind = "async method" if _is_instance_method(statement) else "async callable"
        else:
            kind = "method" if _is_instance_method(statement) else "callable"
        members.append(
            _SurfaceMemberSpec(
                name=statement.name,
                kind=kind,
                start_line=statement.lineno,
                end_line=_end_line(statement),
                node=statement,
            )
        )
    return members


def _class_surface_member_names(
    file_path: Path,
    symbol: str,
    project_root: Path,
    *,
    include_private: bool,
) -> set[str]:
    source = file_path.read_text(encoding="utf-8-sig")
    tree = ast.parse(source, filename=str(file_path))
    class_node = _find_class_node(tree, symbol, file_path)
    return {
        member.name
        for member in _class_surface_members(
            class_node,
            include_private=include_private,
            include_attributes=True,
        )
    }


def _collect_feature_protocol_contracts(project_root: Path) -> tuple[ProtocolContract, ...]:
    features_root = project_root / "src" / "wrong_adventure" / "features"
    contracts: list[ProtocolContract] = []
    for feature_path in sorted(path for path in features_root.iterdir() if path.is_dir()):
        api_root = feature_path / "api"
        if api_root.is_dir():
            candidate_files = sorted(path for path in api_root.rglob("*.py") if path.is_file())
        else:
            public_path = feature_path / "public.py"
            candidate_files = [public_path] if public_path.exists() else []
        for file_path in candidate_files:
            source = file_path.read_text(encoding="utf-8-sig")
            tree = ast.parse(source, filename=str(file_path))
            module_name = _module_name_for_file(file_path, project_root)
            imports = _import_aliases(tree, module_name)
            for statement in tree.body:
                if not isinstance(statement, ast.ClassDef):
                    continue
                resolved_bases = _resolved_class_bases(statement, imports, module_name)
                if not _is_protocol_class(statement, resolved_bases):
                    continue
                members = tuple(
                    member.name
                    for member in _class_surface_members(
                        statement,
                        include_private=False,
                        include_attributes=True,
                    )
                )
                contracts.append(
                    ProtocolContract(
                        feature=feature_path.name,
                        qualified_name=f"{module_name}.{statement.name}",
                        members=members,
                    )
                )
    return tuple(sorted(contracts, key=lambda item: (item.feature, item.qualified_name)))


def _resolved_class_bases(
    class_node: ast.ClassDef,
    imports: dict[str, str],
    module_name: str,
) -> tuple[str, ...]:
    resolved: set[str] = set()
    for base in class_node.bases:
        reference = _resolve_reference(base, imports, module_name) or _render_expr(base)
        if reference:
            resolved.add(reference)
    return tuple(sorted(resolved))


def _is_protocol_class(class_node: ast.ClassDef, resolved_bases: tuple[str, ...]) -> bool:
    if any(_is_protocol_reference(reference) for reference in resolved_bases):
        return True
    return any(isinstance(base, ast.Name) and base.id == "Protocol" for base in class_node.bases)


def _is_protocol_surface_class(
    class_name: str,
    is_protocol: bool,
    base_contracts: tuple[str, ...],
    member_audits: list[ProtocolMemberAudit],
    class_categories: list[str],
) -> bool:
    return bool(
        is_protocol
        or class_name.endswith("Bridge")
        or base_contracts
        or class_categories
        or any(member.replacement_contracts or member.delegation for member in member_audits)
    )


def _default_facade_file(project_root: Path) -> Path | None:
    candidate = project_root / "src" / "wrong_adventure" / "game" / "session.py"
    if candidate.exists():
        return candidate.resolve()
    return None


def _resolve_reference(expression: ast.AST, imports: dict[str, str], module_name: str) -> str | None:
    if isinstance(expression, ast.Name):
        if expression.id == "self":
            return "self"
        if expression.id in imports:
            return imports[expression.id]
        if hasattr(builtins, expression.id):
            return f"builtins.{expression.id}"
        return f"{module_name}.{expression.id}"
    if isinstance(expression, ast.Attribute):
        parent = _resolve_reference(expression.value, imports, module_name)
        if parent is None:
            parent = _render_expr(expression.value)
        if not parent:
            return expression.attr
        return f"{parent}.{expression.attr}"
    return None


def _reference_group(reference: str | None, module_name: str) -> str:
    if reference is None:
        return "unresolved"
    if reference.startswith("self"):
        return "self"
    if ".features." in reference and ".public" in reference:
        return "feature_public"
    if reference.startswith(f"{module_name}."):
        return "same_module"
    module_package, _, _ = module_name.rpartition(".")
    if module_package and reference.startswith(f"{module_package}."):
        return "same_package"
    if reference.startswith("wrong_adventure."):
        return "project_import"
    return "external"


def _sorted_layer_counts(call_sites: tuple[FacadeCallSite, ...]) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = defaultdict(int)
    for call_site in call_sites:
        counts[call_site.layer] += 1
    return tuple(sorted(counts.items()))


def _method_categories(
    call_sites: tuple[FacadeCallSite, ...],
    delegation: FacadeDelegation | None,
) -> tuple[str, ...]:
    categories: list[str] = []
    if delegation is not None:
        categories.append("wrapper")
        if delegation.target_group not in {"self", "unresolved"}:
            categories.append(f"wrapper_to_{delegation.target_group}")
    production_layers = {call_site.layer for call_site in call_sites if call_site.layer != "tests"}
    if not call_sites:
        categories.append("no_callers")
    elif not production_layers:
        categories.append("test_only")
    elif production_layers == {"presentation"}:
        categories.append("presentation_only")
    if any(call_site.access_kind == "attribute" for call_site in call_sites):
        categories.append("attribute_reads")
    return tuple(categories)


def _layer_name(file_path: Path, project_root: Path) -> str:
    try:
        relative = file_path.relative_to(project_root)
    except ValueError:
        relative = file_path
    parts = relative.parts
    if not parts:
        return "other"
    if parts[0] == "tests":
        return "tests"
    if parts[0] == "tools":
        return "tools"
    if parts[0] == "src" and len(parts) >= 4:
        return parts[2]
    return parts[0]


def _render_layer_counts(layer_counts: tuple[tuple[str, int], ...]) -> str:
    if not layer_counts:
        return "none"
    return ",".join(f"{layer}={count}" for layer, count in layer_counts)


def _is_instance_method(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if not function_node.decorator_list:
        return True
    for decorator in function_node.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "staticmethod":
            return False
    return True


def _is_property(function_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(isinstance(decorator, ast.Name) and decorator.id == "property" for decorator in function_node.decorator_list)


def _infer_self_assignment(statement: ast.Assign) -> tuple[str, str] | None:
    if len(statement.targets) != 1 or not _is_self_attribute(statement.targets[0]):
        return None
    field_name = statement.targets[0].attr
    annotation = _inferred_type_from_value(statement.value)
    if annotation is None:
        return None
    return field_name, annotation


def _inferred_type_from_value(value: ast.AST) -> str | None:
    if isinstance(value, ast.Call):
        return _render_expr(value.func)
    return None


def _is_self_attribute(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and isinstance(node.attr, str)
    )


def _is_self_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "self"
    if isinstance(node, ast.Attribute):
        return _is_self_expression(node.value)
    if isinstance(node, ast.Call):
        return _is_self_expression(node.func)
    return False


def _is_protocol_reference(reference: str) -> bool:
    return reference == "typing.Protocol" or reference.endswith(".Protocol") or reference == "Protocol"


def _import_aliases(tree: ast.Module, module_name: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for statement in tree.body:
        if isinstance(statement, ast.Import):
            for alias in statement.names:
                key = alias.asname or alias.name.rsplit(".", 1)[-1]
                aliases[key] = alias.name
        elif isinstance(statement, ast.ImportFrom):
            module = _resolve_imported_module(module_name, statement.module, statement.level)
            for alias in statement.names:
                if alias.name == "*":
                    continue
                key = alias.asname or alias.name
                aliases[key] = f"{module}.{alias.name}" if module else alias.name
    return aliases


def _resolve_imported_module(module_name: str, imported_module: str | None, level: int) -> str:
    if level <= 0:
        return imported_module or ""
    parts = module_name.split(".")
    if parts:
        parts = parts[:-1]
    keep = max(0, len(parts) - (level - 1))
    prefix = parts[:keep]
    if imported_module:
        prefix.extend(imported_module.split("."))
    return ".".join(prefix)


def _collect_python_files(target_path: Path) -> list[Path]:
    if target_path.is_file():
        return [target_path]
    return sorted(
        file_path
        for file_path in target_path.rglob("*.py")
        if "__pycache__" not in file_path.parts
    )


def _module_name_for_file(file_path: Path, project_root: Path) -> str:
    src_root = project_root / "src"
    if file_path.is_relative_to(src_root):
        relative = file_path.relative_to(src_root)
    elif file_path.is_relative_to(project_root):
        relative = file_path.relative_to(project_root)
    else:
        relative = file_path
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = Path(parts[-1]).stem
    return ".".join(parts)


def _code_map_node_payload(node: CodeMapNode) -> dict[str, object]:
    return {
        "children": [_code_map_node_payload(child) for child in node.children],
        "end_line": node.end_line,
        "kind": node.kind,
        "name": node.name,
        "qualified_name": node.qualified_name,
        "start_line": node.start_line,
    }


def _symbol_snapshot_payload(
    snapshot: SymbolSnapshot,
    project_root: Path | None = None,
) -> dict[str, object]:
    return {
        "body_end_line": snapshot.body_end_line,
        "body_hash": snapshot.body_hash,
        "body_indent_columns": snapshot.body_indent_columns,
        "body_source": snapshot.body_source,
        "body_start_line": snapshot.body_start_line,
        "end_line": snapshot.end_line,
        "file_path": _display_path(snapshot.file_path, project_root),
        "kind": snapshot.kind,
        "local_qualified_name": snapshot.local_qualified_name,
        "module_name": snapshot.module_name,
        "name": snapshot.name,
        "node_hash": snapshot.node_hash,
        "node_source": snapshot.node_source,
        "qualified_name": snapshot.qualified_name,
        "shape_hash": snapshot.shape_hash,
        "start_line": snapshot.start_line,
    }


def _edit_result_payload(result: EditResult, project_root: Path | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "changed": result.changed,
        "check_only": result.check_only,
        "file_path": _display_path(result.file_path, project_root),
        "operation": result.operation,
        "target": result.target,
    }
    if result.insert_line is not None:
        payload["insert_line"] = result.insert_line
    if result.new_hash is not None:
        payload["new_hash"] = result.new_hash
    if result.old_hash is not None:
        payload["old_hash"] = result.old_hash
    if result.diff is not None:
        payload["diff"] = result.diff
    if result.snapshot is not None:
        payload["snapshot"] = _symbol_snapshot_payload(result.snapshot, project_root)
    if result.statement is not None:
        payload["statement"] = result.statement
    return payload


def _batch_edit_result_payload(result: BatchEditResult, project_root: Path | None = None) -> dict[str, object]:
    return {
        "changed": any(operation.changed for operation in result.operations),
        "check_only": result.check_only,
        "operation_count": len(result.operations),
        "operations": [_edit_result_payload(operation, project_root) for operation in result.operations],
    }


def _error_payload(error: CodeMapEditError, project_root: Path | None = None) -> dict[str, object]:
    details = error.details
    payload: dict[str, object] = {
        "code": details.code,
        "message": details.message,
    }
    if details.actual_hash is not None:
        payload["actual_hash"] = details.actual_hash
    if details.column is not None:
        payload["column"] = details.column
    if details.current_snapshot is not None:
        payload["current_snapshot"] = _symbol_snapshot_payload(details.current_snapshot, project_root)
    if details.expected_hash is not None:
        payload["expected_hash"] = details.expected_hash
    if details.file_path is not None:
        payload["file_path"] = _display_path(details.file_path, project_root)
    if details.line is not None:
        payload["line"] = details.line
    if details.symbol is not None:
        payload["symbol"] = details.symbol
    return payload


def _statement_kind(statement: ast.AST) -> str:
    if isinstance(statement, ast.ClassDef):
        return "class"
    if isinstance(statement, ast.AsyncFunctionDef):
        return "async function"
    return "function"


def _span_for_node(node: ast.AST, line_offsets: list[int]) -> SourceSpan:
    start_line = int(getattr(node, "lineno"))
    start_column = int(getattr(node, "col_offset"))
    decorator_list = getattr(node, "decorator_list", ())
    if decorator_list:
        first_decorator = min(decorator_list, key=lambda item: (item.lineno, item.col_offset))
        start_line = int(first_decorator.lineno)
        start_column = int(first_decorator.col_offset)
    end_line = _end_line(node)
    end_column = int(getattr(node, "end_col_offset", 0))
    start_offset = _offset_for_location(line_offsets, start_line, start_column)
    end_offset = _offset_for_location(line_offsets, end_line, end_column)
    return SourceSpan(
        start_line=start_line,
        start_column=start_column,
        end_line=end_line,
        end_column=end_column,
        start_offset=start_offset,
        end_offset=end_offset,
    )


def _body_span_for_node(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    line_offsets: list[int],
) -> SourceSpan | None:
    if not node.body:
        return None
    first = node.body[0]
    last = node.body[-1]
    start_line = int(getattr(first, "lineno"))
    start_column = int(getattr(first, "col_offset"))
    end_line = _end_line(last)
    end_column = int(getattr(last, "end_col_offset", 0))
    start_offset = _offset_for_location(line_offsets, start_line, start_column)
    end_offset = _offset_for_location(line_offsets, end_line, end_column)
    return SourceSpan(
        start_line=start_line,
        start_column=start_column,
        end_line=end_line,
        end_column=end_column,
        start_offset=start_offset,
        end_offset=end_offset,
    )


def _line_start_offsets(source: str) -> list[int]:
    offsets = [0]
    running = 0
    for line in source.splitlines(keepends=True):
        running += len(line)
        offsets.append(running)
    return offsets


def _offset_for_location(line_offsets: list[int], line: int, column: int) -> int:
    return line_offsets[line - 1] + column


def _line_prefix(source: str, line: int, column: int) -> str:
    line_text = source.splitlines(keepends=True)[line - 1]
    return line_text[:column]


def _read_source_with_encoding(file_path: Path) -> tuple[str, str]:
    raw = file_path.read_bytes()
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    return file_path.read_text(encoding="utf-8-sig"), encoding


def _render_replacement_at_offset(replacement_text: str, indent_text: str) -> str:
    normalized = replacement_text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = textwrap.dedent(normalized).strip("\n")
    if not normalized.strip():
        raise ValueError("replacement body is empty")
    lines = normalized.split("\n")
    first_line, *remaining_lines = lines
    rendered_lines = [first_line]
    rendered_lines.extend(
        f"{indent_text}{line}" if line else ""
        for line in remaining_lines
    )
    return "\n".join(rendered_lines)


def _render_indented_block(replacement_text: str, indent_text: str, *, ensure_trailing_newline: bool) -> str:
    normalized = replacement_text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = textwrap.dedent(normalized).strip("\n")
    if not normalized.strip():
        raise ValueError("replacement block is empty")
    rendered = "\n".join(
        f"{indent_text}{line}" if line else ""
        for line in normalized.split("\n")
    )
    if ensure_trailing_newline:
        return rendered + "\n"
    return rendered


def _shape_hash_for_source(kind: str, name: str, source_text: str) -> str:
    tree = ast.parse(source_text, mode="exec")
    if len(tree.body) != 1:
        return _hash_text(json.dumps({"kind": kind, "name": name}, sort_keys=True))
    statement = tree.body[0]
    payload = _shape_payload_for_node(statement)
    return _hash_text(json.dumps(payload, sort_keys=True))


def _shape_payload_for_node(node: ast.stmt) -> dict[str, object]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return {
            "args": [_shape_payload_for_arguments(node.args)],
            "decorators": [_render_expr(item) for item in node.decorator_list],
            "kind": "async function" if isinstance(node, ast.AsyncFunctionDef) else "function",
            "name": node.name,
            "returns": _render_expr(node.returns) if node.returns is not None else None,
        }
    if isinstance(node, ast.ClassDef):
        return {
            "bases": [_render_expr(base) for base in node.bases],
            "decorators": [_render_expr(item) for item in node.decorator_list],
            "keywords": [
                f"{keyword.arg}={_render_expr(keyword.value)}" if keyword.arg else _render_expr(keyword.value)
                for keyword in node.keywords
            ],
            "kind": "class",
            "name": node.name,
        }
    return {"kind": node.__class__.__name__}


def _shape_payload_for_arguments(arguments: ast.arguments) -> dict[str, object]:
    return {
        "args": [_shape_payload_for_arg(argument) for argument in arguments.args],
        "kwarg": None if arguments.kwarg is None else _shape_payload_for_arg(arguments.kwarg),
        "kwonlyargs": [_shape_payload_for_arg(argument) for argument in arguments.kwonlyargs],
        "posonlyargs": [_shape_payload_for_arg(argument) for argument in arguments.posonlyargs],
        "vararg": None if arguments.vararg is None else _shape_payload_for_arg(arguments.vararg),
    }


def _shape_payload_for_arg(argument: ast.arg) -> dict[str, object]:
    return {
        "annotation": None if argument.annotation is None else _render_expr(argument.annotation),
        "name": argument.arg,
    }


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _render_node(node: CodeMapNode, depth: int) -> list[str]:
    indent = "  " * depth
    lines = [f"{indent}{node.kind} {node.name}: {node.start_line}-{node.end_line}"]
    for child in node.children:
        lines.extend(_render_node(child, depth + 1))
    return lines


def _display_path(file_path: Path, project_root: Path | None) -> str:
    if project_root is None:
        return str(file_path)
    try:
        return str(file_path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        return str(file_path)


def _type_reference_names(annotation: str) -> set[str]:
    try:
        node = ast.parse(annotation, mode="eval")
    except SyntaxError:
        return {annotation}
    names: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name):
            names.add(inner.id)
        elif isinstance(inner, ast.Attribute):
            names.add(_render_expr(inner))
        elif isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            names.update(_type_reference_names(inner.value))
    return names


def _render_expr(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = _render_expr(node.value)
            return f"{parent}.{node.attr}" if parent else node.attr
        return ""


def _alias_for_class(qualified_name: str) -> str:
    return "cls_" + "".join(character if character.isalnum() else "_" for character in qualified_name)


def _end_line(node: ast.AST) -> int:
    end_line = getattr(node, "end_lineno", None)
    if end_line is not None:
        return int(end_line)
    return int(getattr(node, "lineno"))
