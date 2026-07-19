from __future__ import annotations

import difflib
import hashlib
import json
import re
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


_SIMPLE_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass(frozen=True)
class YamlMapNode:
    label: str
    kind: str
    optional: bool
    children: tuple["YamlMapNode", ...] = ()


@dataclass(frozen=True)
class YamlMapReport:
    file_path: Path
    root_kind: str
    nodes: tuple[YamlMapNode, ...]


@dataclass(frozen=True)
class ProjectMapEntry:
    file_path: Path
    root_kind: str
    summary: str
    report: YamlMapReport | None = None


@dataclass(frozen=True)
class ProjectMapReport:
    target_path: Path
    entries: tuple[ProjectMapEntry, ...]
    deep: bool


@dataclass(frozen=True)
class PathSnapshot:
    file_path: Path
    path: str
    kind: str
    value_hash: str
    value: Any


@dataclass(frozen=True)
class EditResult:
    file_path: Path
    operation: str
    target: str
    changed: bool
    check_only: bool
    old_hash: str | None = None
    new_hash: str | None = None
    diff: str | None = None


@dataclass(frozen=True)
class ParseCheckResult:
    file_path: Path
    ok: bool
    error_message: str | None = None
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True)
class YamlMapErrorDetails:
    code: str
    message: str
    file_path: Path | None = None
    path: str | None = None
    expected_hash: str | None = None
    actual_hash: str | None = None


class YamlMapEditError(ValueError):
    def __init__(self, details: YamlMapErrorDetails) -> None:
        super().__init__(details.message)
        self.details = details


@dataclass
class _ObservedNode:
    labels: OrderedDict[str, str] = field(default_factory=OrderedDict)
    kinds: set[str] = field(default_factory=set)
    scalar_types: set[str] = field(default_factory=set)
    list_lengths: list[int] = field(default_factory=list)
    map_occurrences: int = 0
    child_counts: dict[str, int] = field(default_factory=dict)


def build_yaml_map(file_path: Path) -> YamlMapReport:
    data = _load_yaml_file(file_path)
    observed = _observe_paths(data)
    root = observed[""]
    nodes = tuple(_build_render_nodes(observed, "", root_kind=_kind_display(root)))
    return YamlMapReport(file_path=file_path, root_kind=_kind_display(root), nodes=nodes)


def render_yaml_map(file_path: Path, project_root: Path | None = None) -> str:
    report = build_yaml_map(file_path)
    lines = [_display_path(report.file_path, project_root)]
    for node in report.nodes:
        lines.extend(_render_map_node(node, depth=0))
    return "\n".join(lines)


def render_yaml_map_json(file_path: Path, project_root: Path | None = None) -> str:
    report = build_yaml_map(file_path)
    return json.dumps(_yaml_map_report_payload(report, project_root), indent=2, sort_keys=True)


def project_map(target_path: Path, project_root: Path, *, deep: bool = False) -> ProjectMapReport:
    yaml_files = _collect_yaml_files(target_path)
    entries: list[ProjectMapEntry] = []
    for file_path in yaml_files:
        data = _load_yaml_file(file_path)
        summary = _summarize_root_value(data)
        report = build_yaml_map(file_path) if deep else None
        entries.append(
            ProjectMapEntry(
                file_path=file_path,
                root_kind=_value_kind(data),
                summary=summary,
                report=report,
            )
        )
    return ProjectMapReport(target_path=target_path, entries=tuple(entries), deep=deep)


def render_project_map(report: ProjectMapReport, project_root: Path | None = None) -> str:
    lines = [f"{_display_path(report.target_path, project_root)} :: yaml files={len(report.entries)}"]
    for entry in report.entries:
        label = _display_path(entry.file_path, project_root)
        lines.append(f"- {label} :: {entry.summary}")
        if report.deep and entry.report is not None:
            for node in entry.report.nodes:
                for rendered in _render_map_node(node, depth=1):
                    lines.append(rendered)
    return "\n".join(lines)


def render_project_map_json(report: ProjectMapReport, project_root: Path | None = None) -> str:
    return json.dumps(
        {
            "deep": report.deep,
            "entries": [_project_map_entry_payload(entry, project_root) for entry in report.entries],
            "target_path": _display_path(report.target_path, project_root),
        },
        indent=2,
        sort_keys=True,
    )


def path_get(file_path: Path, path_text: str) -> PathSnapshot:
    data = _load_yaml_file(file_path)
    segments = _parse_yaml_path(path_text)
    value = _resolve_segments(data, segments)
    return PathSnapshot(
        file_path=file_path,
        path=_render_path(segments),
        kind=_value_kind(value),
        value_hash=_hash_value(value),
        value=value,
    )


def render_path_snapshot(snapshot: PathSnapshot, project_root: Path | None = None) -> str:
    label = _display_path(snapshot.file_path, project_root)
    lines = [
        f"{label} :: path-get",
        f"path: {snapshot.path}",
        f"kind: {snapshot.kind}",
        f"hash: {snapshot.value_hash}",
        "value:",
        json.dumps(snapshot.value, ensure_ascii=False, indent=2, sort_keys=True),
    ]
    return "\n".join(lines)


def render_path_snapshot_json(snapshot: PathSnapshot, project_root: Path | None = None) -> str:
    return json.dumps(_path_snapshot_payload(snapshot, project_root), indent=2, sort_keys=True)


def path_set(
    file_path: Path,
    path_text: str,
    expected_hash: str,
    value: object,
    *,
    check_only: bool = False,
) -> EditResult:
    source, encoding = _read_source_with_encoding(file_path)
    data = _load_yaml_text(source, file_path=file_path)
    segments = _parse_yaml_path(path_text)
    current_value = _resolve_segments(data, segments)
    _assert_hash_matches(file_path, segments, current_value, expected_hash)
    updated_data = _clone_value(data)
    updated_current = _resolve_parent_and_key(updated_data, segments)
    if updated_current is None:
        updated_data = _clone_value(value)
    else:
        parent, key = updated_current
        if isinstance(parent, list):
            assert isinstance(key, int)
            parent[key] = _clone_value(value)
        else:
            assert isinstance(key, str)
            parent[key] = _clone_value(value)
    return _finalize_edit(
        file_path,
        source,
        updated_data,
        encoding,
        operation="path-set",
        target=_render_path(segments),
        old_hash=_hash_value(current_value),
        new_hash=_hash_value(value),
        check_only=check_only,
    )


def insert_item(
    file_path: Path,
    path_text: str,
    expected_hash: str,
    value: object,
    *,
    key: str | None = None,
    index: int | None = None,
    check_only: bool = False,
) -> EditResult:
    source, encoding = _read_source_with_encoding(file_path)
    data = _load_yaml_text(source, file_path=file_path)
    segments = _parse_yaml_path(path_text)
    container = _resolve_segments(data, segments)
    _assert_hash_matches(file_path, segments, container, expected_hash)
    updated_data = _clone_value(data)
    updated_container = _resolve_segments(updated_data, segments)
    target = _render_path(segments)
    if isinstance(updated_container, dict):
        if key is None:
            raise ValueError("mapping insert requires --key")
        if index is not None:
            raise ValueError("mapping insert does not accept --index")
        if key in updated_container:
            raise ValueError(f"path '{target}' already contains key '{key}'")
        updated_container[key] = _clone_value(value)
        rendered_target = f"{target}{_render_key_segment(key, first=not segments)}"
    elif isinstance(updated_container, list):
        if key is not None:
            raise ValueError("list insert does not accept --key")
        insert_at = len(updated_container) if index is None else index
        if insert_at < 0 or insert_at > len(updated_container):
            raise ValueError(f"list insert index out of range: {insert_at}")
        updated_container.insert(insert_at, _clone_value(value))
        rendered_target = f"{target}[{insert_at}]" if target != "<root>" else f"<root>[{insert_at}]"
    else:
        raise ValueError(f"path '{target}' is not a container")
    return _finalize_edit(
        file_path,
        source,
        updated_data,
        encoding,
        operation="item-insert",
        target=rendered_target,
        old_hash=_hash_value(container),
        new_hash=_hash_value(updated_container),
        check_only=check_only,
    )


def path_delete(
    file_path: Path,
    path_text: str,
    expected_hash: str,
    *,
    check_only: bool = False,
) -> EditResult:
    source, encoding = _read_source_with_encoding(file_path)
    data = _load_yaml_text(source, file_path=file_path)
    segments = _parse_yaml_path(path_text)
    if not segments:
        raise ValueError("cannot delete <root>")
    current_value = _resolve_segments(data, segments)
    _assert_hash_matches(file_path, segments, current_value, expected_hash)
    updated_data = _clone_value(data)
    parent, key = _require_parent_and_key(updated_data, segments)
    if isinstance(parent, list):
        assert isinstance(key, int)
        del parent[key]
    else:
        assert isinstance(key, str)
        del parent[key]
    return _finalize_edit(
        file_path,
        source,
        updated_data,
        encoding,
        operation="path-delete",
        target=_render_path(segments),
        old_hash=_hash_value(current_value),
        new_hash=None,
        check_only=check_only,
    )


def render_edit_result(result: EditResult, project_root: Path | None = None) -> str:
    parts = [
        f"{_display_path(result.file_path, project_root)} :: {result.operation}",
        f"target={result.target}",
        f"changed={str(result.changed).lower()}",
        f"check_only={str(result.check_only).lower()}",
    ]
    if result.old_hash is not None:
        parts.append(f"old_hash={result.old_hash}")
    if result.new_hash is not None:
        parts.append(f"new_hash={result.new_hash}")
    rendered = " ".join(parts)
    if result.diff:
        return rendered + "\n" + result.diff
    return rendered


def render_edit_result_json(result: EditResult, project_root: Path | None = None) -> str:
    payload: dict[str, object] = {
        "changed": result.changed,
        "check_only": result.check_only,
        "file_path": _display_path(result.file_path, project_root),
        "operation": result.operation,
        "target": result.target,
    }
    if result.diff is not None:
        payload["diff"] = result.diff
    if result.new_hash is not None:
        payload["new_hash"] = result.new_hash
    if result.old_hash is not None:
        payload["old_hash"] = result.old_hash
    return json.dumps(payload, indent=2, sort_keys=True)


def parse_check(file_path: Path) -> ParseCheckResult:
    source = file_path.read_text(encoding="utf-8-sig")
    try:
        _load_yaml_text(source, file_path=file_path)
    except yaml.YAMLError as error:
        line = None
        column = None
        mark = getattr(error, "problem_mark", None)
        if mark is not None:
            line = int(mark.line) + 1
            column = int(mark.column)
        return ParseCheckResult(
            file_path=file_path,
            ok=False,
            error_message=str(error).strip(),
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


def render_error_json(error: YamlMapEditError, project_root: Path | None = None) -> str:
    details = error.details
    payload: dict[str, object] = {
        "code": details.code,
        "message": details.message,
    }
    if details.actual_hash is not None:
        payload["actual_hash"] = details.actual_hash
    if details.expected_hash is not None:
        payload["expected_hash"] = details.expected_hash
    if details.file_path is not None:
        payload["file_path"] = _display_path(details.file_path, project_root)
    if details.path is not None:
        payload["path"] = details.path
    return json.dumps(payload, indent=2, sort_keys=True)


def compact_help() -> str:
    return "\n".join(
        [
            "yaml_map.py help",
            "yaml_map.py map <yaml_file> [--json]",
            "yaml_map.py project-map [path] [--deep] [--json]",
            "yaml_map.py path-get <yaml_file> --path <yaml_path> [--json]",
            "yaml_map.py path-set <yaml_file> --path <yaml_path> --expect-hash <sha256> (--value-json <json> | --value-file <path> | --value-stdin) [--check-only] [--json]",
            "yaml_map.py item-insert <yaml_file> --path <yaml_path> --expect-hash <sha256> [--key <name> | --index <n>] (--value-json <json> | --value-file <path> | --value-stdin) [--check-only] [--json]",
            "yaml_map.py path-delete <yaml_file> --path <yaml_path> --expect-hash <sha256> [--check-only] [--json]",
            "yaml_map.py parse-check <yaml_file> [--json]",
        ]
    )


def _observe_paths(value: Any) -> dict[str, _ObservedNode]:
    observed: dict[str, _ObservedNode] = {}

    def ensure(path: str) -> _ObservedNode:
        node = observed.get(path)
        if node is None:
            node = _ObservedNode()
            observed[path] = node
        return node

    def visit(node: Any, path: str) -> None:
        observed_node = ensure(path)
        kind = _value_kind(node)
        observed_node.kinds.add(kind)
        if isinstance(node, dict):
            observed_node.map_occurrences += 1
            for key, child in node.items():
                child_label = str(key)
                child_path = _join_normalized_path(path, child_label)
                if child_label not in observed_node.labels:
                    observed_node.labels[child_label] = child_path
                observed_node.child_counts[child_label] = observed_node.child_counts.get(child_label, 0) + 1
                visit(child, child_path)
            return
        if isinstance(node, list):
            observed_node.list_lengths.append(len(node))
            child_path = _join_normalized_path(path, "[]")
            if "[]" not in observed_node.labels:
                observed_node.labels["[]"] = child_path
            ensure(child_path)
            for child in node:
                visit(child, child_path)
            return
        observed_node.scalar_types.add(_scalar_type_name(node))

    visit(value, "")
    return observed


def _build_render_nodes(observed: dict[str, _ObservedNode], parent_path: str, *, root_kind: str | None = None) -> list[YamlMapNode]:
    parent = observed[parent_path]
    nodes: list[YamlMapNode] = []
    for label, child_path in parent.labels.items():
        child = observed[child_path]
        optional = False
        if label != "[]" and parent.map_occurrences > 0:
            optional = parent.child_counts.get(label, 0) < parent.map_occurrences
        nodes.append(
            YamlMapNode(
                label=_render_tree_label(label),
                kind=_kind_display(child),
                optional=optional,
                children=tuple(_build_render_nodes(observed, child_path)),
            )
        )
    return nodes


def _render_map_node(node: YamlMapNode, depth: int) -> list[str]:
    indent = "  " * depth
    optional = " optional" if node.optional else ""
    lines = [f"{indent}{node.label}: {node.kind}{optional}"]
    for child in node.children:
        lines.extend(_render_map_node(child, depth + 1))
    return lines


def _yaml_map_report_payload(report: YamlMapReport, project_root: Path | None) -> dict[str, object]:
    return {
        "file_path": _display_path(report.file_path, project_root),
        "nodes": [_yaml_map_node_payload(node) for node in report.nodes],
        "root_kind": report.root_kind,
    }


def _yaml_map_node_payload(node: YamlMapNode) -> dict[str, object]:
    return {
        "children": [_yaml_map_node_payload(child) for child in node.children],
        "kind": node.kind,
        "label": node.label,
        "optional": node.optional,
    }


def _project_map_entry_payload(entry: ProjectMapEntry, project_root: Path | None) -> dict[str, object]:
    payload: dict[str, object] = {
        "file_path": _display_path(entry.file_path, project_root),
        "root_kind": entry.root_kind,
        "summary": entry.summary,
    }
    if entry.report is not None:
        payload["report"] = _yaml_map_report_payload(entry.report, project_root)
    return payload


def _path_snapshot_payload(snapshot: PathSnapshot, project_root: Path | None) -> dict[str, object]:
    return {
        "file_path": _display_path(snapshot.file_path, project_root),
        "kind": snapshot.kind,
        "path": snapshot.path,
        "value": snapshot.value,
        "value_hash": snapshot.value_hash,
    }


def _kind_display(node: _ObservedNode) -> str:
    if node.kinds == {"dict"}:
        return "map"
    if node.kinds == {"list"}:
        if not node.list_lengths:
            return "list"
        lengths = sorted(set(node.list_lengths))
        if len(lengths) == 1:
            return f"list len={lengths[0]}"
        return "list lens=" + ",".join(str(length) for length in lengths)
    if node.kinds and node.kinds <= {"str", "int", "float", "bool", "null"}:
        return "|".join(sorted(node.scalar_types))
    kinds = sorted("map" if kind == "dict" else kind for kind in node.kinds)
    return "|".join(kinds)


def _summarize_root_value(value: Any) -> str:
    if isinstance(value, dict):
        keys = ",".join(str(key) for key in value.keys())
        return f"map keys={keys}" if keys else "map"
    if isinstance(value, list):
        return f"list len={len(value)}"
    return _scalar_type_name(value)


def _collect_yaml_files(target_path: Path) -> list[Path]:
    if target_path.is_file():
        if target_path.suffix.lower() not in {".yaml", ".yml"}:
            raise ValueError(f"not a YAML file: {target_path}")
        return [target_path]
    return sorted(
        path
        for path in target_path.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".yaml", ".yml"}
        and "__pycache__" not in path.parts
        and ".git" not in path.parts
    )


def _join_normalized_path(parent_path: str, label: str) -> str:
    if label == "[]":
        return f"{parent_path}[]" if parent_path else "[]"
    if not parent_path:
        return _render_key_segment(label, first=True)
    if parent_path.endswith("[]"):
        return f"{parent_path}{_render_key_segment(label, first=False)}"
    return f"{parent_path}{_render_key_segment(label, first=False)}"


def _parse_yaml_path(path_text: str) -> tuple[str | int, ...]:
    text = path_text.strip()
    if text in {"", ".", "<root>"}:
        return ()
    segments: list[str | int] = []
    index = 0
    while index < len(text):
        character = text[index]
        if character == ".":
            index += 1
            continue
        if character == "[":
            end = _find_closing_bracket(text, index)
            inner = text[index + 1 : end].strip()
            if not inner:
                raise ValueError(f"empty bracket segment in path '{path_text}'")
            if inner[0] in {'"', "'"}:
                segments.append(_parse_quoted_key(inner, path_text))
            else:
                try:
                    segments.append(int(inner))
                except ValueError as error:
                    raise ValueError(f"invalid list index '{inner}' in path '{path_text}'") from error
            index = end + 1
            continue
        start = index
        while index < len(text) and text[index] not in ".[":
            index += 1
        key = text[start:index]
        if not key:
            raise ValueError(f"invalid path '{path_text}'")
        segments.append(key)
    return tuple(segments)


def _find_closing_bracket(text: str, start: int) -> int:
    quote: str | None = None
    escaped = False
    for index in range(start + 1, len(text)):
        character = text[index]
        if quote is not None:
            if escaped:
                escaped = False
                continue
            if character == "\\":
                escaped = True
                continue
            if character == quote:
                quote = None
            continue
        if character in {'"', "'"}:
            quote = character
            continue
        if character == "]":
            return index
    raise ValueError(f"unclosed bracket segment in path '{text}'")


def _parse_quoted_key(inner: str, path_text: str) -> str:
    quote = inner[0]
    if len(inner) < 2 or inner[-1] != quote:
        raise ValueError(f"invalid quoted key in path '{path_text}'")
    if quote == '"':
        return str(json.loads(inner))
    content = inner[1:-1].replace("\\\\", "\\").replace("\\'", "'")
    return content


def _resolve_segments(node: Any, segments: tuple[str | int, ...]) -> Any:
    current = node
    for segment in segments:
        if isinstance(segment, int):
            if not isinstance(current, list):
                raise ValueError(f"path '{_render_path(segments)}' expected list before index [{segment}]")
            try:
                current = current[segment]
            except IndexError as error:
                raise ValueError(f"path '{_render_path(segments)}' missing index [{segment}]") from error
            continue
        if not isinstance(current, dict):
            raise ValueError(f"path '{_render_path(segments)}' expected mapping before key '{segment}'")
        if segment not in current:
            raise ValueError(f"path '{_render_path(segments)}' missing key '{segment}'")
        current = current[segment]
    return current


def _resolve_parent_and_key(node: Any, segments: tuple[str | int, ...]) -> tuple[Any, str | int] | None:
    if not segments:
        return None
    parent = _resolve_segments(node, segments[:-1])
    return parent, segments[-1]


def _require_parent_and_key(node: Any, segments: tuple[str | int, ...]) -> tuple[Any, str | int]:
    resolved = _resolve_parent_and_key(node, segments)
    if resolved is None:
        raise ValueError("expected non-root path")
    return resolved


def _assert_hash_matches(
    file_path: Path,
    segments: tuple[str | int, ...],
    value: Any,
    expected_hash: str,
) -> None:
    actual_hash = _hash_value(value)
    if actual_hash != expected_hash:
        raise YamlMapEditError(
            YamlMapErrorDetails(
                code="hash-mismatch",
                message=f"path '{_render_path(segments)}' changed; expected {expected_hash} but found {actual_hash}",
                file_path=file_path,
                path=_render_path(segments),
                expected_hash=expected_hash,
                actual_hash=actual_hash,
            )
        )


def _finalize_edit(
    file_path: Path,
    old_source: str,
    updated_data: Any,
    encoding: str,
    *,
    operation: str,
    target: str,
    old_hash: str | None,
    new_hash: str | None,
    check_only: bool,
) -> EditResult:
    new_source = _dump_yaml(updated_data)
    diff = _render_unified_diff(old_source, new_source, file_path)
    changed = old_source != new_source
    if changed and not check_only:
        file_path.write_text(new_source, encoding=encoding, newline="\n")
    return EditResult(
        file_path=file_path,
        operation=operation,
        target=target,
        changed=changed,
        check_only=check_only,
        old_hash=old_hash,
        new_hash=new_hash,
        diff=diff if diff else None,
    )


def _load_yaml_file(file_path: Path) -> Any:
    return _load_yaml_text(file_path.read_text(encoding="utf-8-sig"), file_path=file_path)


def _load_yaml_text(source: str, *, file_path: Path | None = None) -> Any:
    value = yaml.safe_load(source)
    if value is None:
        return {}
    return value


def _read_source_with_encoding(file_path: Path) -> tuple[str, str]:
    raw = file_path.read_bytes()
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
    return file_path.read_text(encoding="utf-8-sig"), encoding


def _dump_yaml(value: Any) -> str:
    rendered = yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
    return rendered if rendered.endswith("\n") else rendered + "\n"


def _render_unified_diff(old_source: str, new_source: str, file_path: Path) -> str:
    return "\n".join(
        difflib.unified_diff(
            old_source.splitlines(),
            new_source.splitlines(),
            fromfile=str(file_path),
            tofile=str(file_path),
            lineterm="",
        )
    )


def _hash_value(value: Any) -> str:
    normalized = json.dumps(_normalize_value(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _normalize_value(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [_normalize_value(inner) for inner in value]
    return value


def _clone_value(value: Any) -> Any:
    return json.loads(json.dumps(_normalize_value(value), ensure_ascii=False))


def _render_path(segments: tuple[str | int, ...]) -> str:
    if not segments:
        return "<root>"
    parts: list[str] = []
    for index, segment in enumerate(segments):
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
            continue
        parts.append(_render_key_segment(segment, first=index == 0))
    return "".join(parts)


def _render_key_segment(key: str, *, first: bool) -> str:
    if _SIMPLE_KEY_RE.match(key):
        return key if first else f".{key}"
    return f"[{json.dumps(key, ensure_ascii=False)}]"


def _render_tree_label(label: str) -> str:
    if label == "[]":
        return label
    if _SIMPLE_KEY_RE.match(label):
        return label
    return f"[{json.dumps(label, ensure_ascii=False)}]"


def _value_kind(value: Any) -> str:
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    return _scalar_type_name(value)


def _scalar_type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    return type(value).__name__


def _display_path(file_path: Path, project_root: Path | None) -> str:
    if project_root is None:
        return str(file_path)
    try:
        return str(file_path.relative_to(project_root)).replace("\\", "/")
    except ValueError:
        return str(file_path)
