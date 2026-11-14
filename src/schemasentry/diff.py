"""Structural comparison of snapshots. No risk verdicts or SQL execution."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from pydantic import Field, ValidationError

from schemasentry.errors import ToolError
from schemasentry.snapshot import Column, Snapshot, SnapshotModel, Table


class Change(SnapshotModel):
    schema_name: str = Field(alias="schema")
    table: str
    object: str
    kind: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


class Comparison(SnapshotModel):
    schema_version: int = 1
    changes: list[Change]
    warnings: list[str] = Field(default_factory=list)


def _unique[T: SnapshotModel](items: Iterable[T], key: Callable[[T], str]) -> dict[str, T]:
    result: dict[str, T] = {}
    for item in items:
        name = key(item)
        if name in result:
            raise ToolError(f"ambiguous snapshot: duplicate object {name!r}")
        result[name] = item
    return result


def _column(column: Column) -> dict[str, Any]:
    # Ordinal is physical presentation, not the identity of a column.
    return column.model_dump(by_alias=True, exclude={"ordinal"})


def _table(table: Table) -> dict[str, Any]:
    result = table.model_dump(by_alias=True, exclude={"row_estimate", "total_bytes"})
    result["columns"] = sorted((_column(c) for c in table.columns), key=lambda c: c["name"])
    for field in ("constraints", "indexes"):
        result[field].sort(key=lambda obj: obj["name"])
    return result


def load_snapshot(path: Path) -> Snapshot:
    try:
        # Bound accidental/wrong-file inputs while allowing large real schemas.
        with path.open("rb") as handle:
            raw = handle.read(64 * 1024 * 1024 + 1)
        if len(raw) > 64 * 1024 * 1024:
            raise ToolError("snapshot exceeds 64 MiB")
        payload = json.loads(raw, object_pairs_hook=_json_object)
        if (
            not isinstance(payload, dict)
            or type(payload.get("schemaVersion")) is not int
            or payload["schemaVersion"] != 1
        ):
            raise ToolError("unsupported or missing snapshot schemaVersion (expected 1)")
        snapshot = Snapshot.model_validate(payload)
    except (OSError, ValueError, ValidationError, RecursionError) as exc:
        raise ToolError(f"cannot read valid snapshot {path.name}: {type(exc).__name__}") from None
    _validate(snapshot)
    return snapshot


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ToolError("snapshot contains duplicate JSON fields")
        result[key] = value
    return result


def _validate(snapshot: Snapshot) -> None:
    if (
        type(snapshot.schema_version) is not int
        or snapshot.schema_version != 1
        or snapshot.dialect != "postgres"
    ):
        raise ToolError("comparison requires schemaVersion 1 PostgreSQL snapshots")
    _unique(snapshot.tables, lambda t: json.dumps([t.schema_name, t.name]))
    _unique(snapshot.sequences, lambda s: json.dumps([s.schema_name, s.name]))
    for table in snapshot.tables:
        _unique(table.columns, lambda c: c.name)
        _unique(table.constraints, lambda c: c.name)
        _unique(table.indexes, lambda i: i.name)


def _semantic_objects(
    before: list[Any], after: list[Any], schema: str, table: str, kind: str
) -> list[Change]:
    # Match content first, independent of names. This also ignores backing-index
    # renames that PostgreSQL performs when renaming a UNIQUE/PRIMARY KEY constraint.
    old = {obj.name: obj for obj in before}
    new = {obj.name: obj for obj in after}
    content: dict[str, list[str]] = defaultdict(list)
    for name in sorted(new):
        fingerprint = json.dumps(new[name].model_dump(exclude={"name"}), sort_keys=True)
        content[fingerprint].append(name)
    for name in sorted(list(old)):
        fingerprint = json.dumps(old[name].model_dump(exclude={"name"}), sort_keys=True)
        matches = content[fingerprint]
        if matches:
            del old[name]
            del new[matches.pop()]
    changes = []
    for name in sorted(old.keys() | new.keys()):
        left = old[name].model_dump(by_alias=True) if name in old else None
        right = new[name].model_dump(by_alias=True) if name in new else None
        action = (
            "changed"
            if left is not None and right is not None
            else ("removed" if left is not None else "added")
        )
        changes.append(
            Change(
                schema=schema,
                table=table,
                object=name,
                kind=f"{kind}_{action}",
                before=left,
                after=right,
            )
        )
    return changes


def compare(before: Snapshot, after: Snapshot) -> Comparison:
    _validate(before)
    _validate(after)
    old = {(t.schema_name, t.name): t for t in before.tables}
    new = {(t.schema_name, t.name): t for t in after.tables}
    changes: list[Change] = []
    warnings: set[str] = set()
    for snapshot in (before, after):
        for table in snapshot.tables:
            if any(c.definition is None for c in table.constraints):
                warnings.add(
                    "Legacy constraint definitions are incomplete; "
                    "recapture both snapshots for full comparison."
                )
            if any(i.keys is None for i in table.indexes):
                warnings.add(
                    "Legacy index keys omit ordering/opclasses; "
                    "recapture both snapshots for full comparison."
                )
    for schema, name in sorted(old.keys() | new.keys()):
        left, right = old.get((schema, name)), new.get((schema, name))
        if left is None or right is None:
            changes.append(
                Change(
                    schema=schema,
                    table=name,
                    object=name,
                    kind="table_added" if left is None else "table_removed",
                    before=_table(left) if left else None,
                    after=_table(right) if right else None,
                )
            )
            continue
        old_columns = {c.name: c for c in left.columns}
        new_columns = {c.name: c for c in right.columns}
        for column in sorted(old_columns.keys() | new_columns.keys()):
            a = _column(old_columns[column]) if column in old_columns else None
            b = _column(new_columns[column]) if column in new_columns else None
            if a == b:
                continue
            action = (
                "changed"
                if a is not None and b is not None
                else ("removed" if a is not None else "added")
            )
            changes.append(
                Change(
                    schema=schema,
                    table=name,
                    object=column,
                    kind=f"column_{action}",
                    before=a,
                    after=b,
                )
            )
        changes.extend(
            _semantic_objects(left.constraints, right.constraints, schema, name, "constraint")
        )
        changes.extend(_semantic_objects(left.indexes, right.indexes, schema, name, "index"))
    changes.sort(key=lambda c: (c.schema_name, c.table, c.object, c.kind))
    return Comparison(changes=changes, warnings=sorted(warnings))


def comparison_json(comparison: Comparison) -> str:
    return json.dumps(comparison.model_dump(by_alias=True), ensure_ascii=False, indent=2) + "\n"
