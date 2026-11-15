"""Strict, bounded rename declarations; hints never establish data preservation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ConfigDict, Field, StrictInt, StrictStr, field_validator

from schemasentry.errors import ToolError
from schemasentry.evidence import EvidenceModel
from schemasentry.snapshot import Snapshot

MAX_HINT_BYTES = 64 * 1024
MAX_RENAMES = 128


class ColumnRename(EvidenceModel):
    model_config = ConfigDict(populate_by_name=False, validate_by_name=False)

    schema_name: StrictStr = Field(alias="schema", min_length=1)
    table: StrictStr = Field(min_length=1)
    from_column: StrictStr = Field(alias="from", min_length=1)
    to_column: StrictStr = Field(alias="to", min_length=1)

    @field_validator("schema_name", "table", "from_column", "to_column")
    @classmethod
    def valid_identifier(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("rename hint identifiers must not contain NUL")
        return value


class RenameHints(EvidenceModel):
    model_config = ConfigDict(populate_by_name=False, validate_by_name=False)

    schema_version: StrictInt
    renames: tuple[ColumnRename, ...] = Field(max_length=MAX_RENAMES)

    @field_validator("schema_version")
    @classmethod
    def version_one(cls, value: int) -> int:
        if value != 1:
            raise ValueError("rename hints require schemaVersion 1")
        return value


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate rename hint fields")
        result[key] = value
    return result


def load_hints(path: Path) -> RenameHints:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_HINT_BYTES + 1)
        if len(raw) > MAX_HINT_BYTES:
            raise ToolError("rename hint file exceeds 64 KiB")
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_json_object)
        return RenameHints.model_validate(payload)
    except (OSError, ValueError, RecursionError):
        raise ToolError(
            "cannot read valid rename hints (strict JSON schemaVersion 1 required)"
        ) from None


def validate_hints(
    hints: RenameHints | None, before: Snapshot, after: Snapshot
) -> tuple[ColumnRename, ...]:
    """Require an actual, unambiguous drop/add in a table present in both inputs."""
    if hints is None:
        return ()
    old = {(t.schema_name, t.name): {c.name for c in t.columns} for t in before.tables}
    new = {(t.schema_name, t.name): {c.name for c in t.columns} for t in after.tables}
    sources: set[tuple[str, str, str]] = set()
    targets: set[tuple[str, str, str]] = set()
    for rename in hints.renames:
        key = (rename.schema_name, rename.table)
        source = (*key, rename.from_column)
        target = (*key, rename.to_column)
        if source in sources or target in targets:
            raise ToolError("rename hints contain duplicate or colliding endpoints")
        sources.add(source)
        targets.add(target)
        if (
            key not in old
            or key not in new
            or rename.from_column not in old[key]
            or rename.from_column in new[key]
            or rename.to_column not in new[key]
            or rename.to_column in old[key]
        ):
            raise ToolError(
                "rename hint must pair an actual column removal and addition in one table"
            )
    if sources & targets:
        raise ToolError("rename hints contain cycles or colliding endpoints")
    return tuple(
        sorted(hints.renames, key=lambda r: (r.schema_name, r.table, r.from_column, r.to_column))
    )
