"""Snapshot model and deterministic serialisation.

A snapshot is the schema state of one database at one moment, as data. It is
the only input the comparison engine will ever receive, which is what keeps
comparison testable without a database.

Determinism rules:

* tables are ordered by (schema, name), columns by ordinal, constraints by
  (kind, name), indexes and sequences by name, schemas and extensions
  alphabetically;
* every field is written, including nulls, so a missing value is visible;
* the JSON is UTF-8, two-space indented, with a trailing newline and no
  platform-dependent newline translation.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

SNAPSHOT_SCHEMA_VERSION = 1


class SnapshotModel(BaseModel):
    """Base model: camelCase on the wire, snake_case in Python, no extras."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        frozen=True,
        extra="forbid",
    )


class Column(SnapshotModel):
    """One column. `type` is what the server reports, verbatim."""

    name: str
    ordinal: int = Field(ge=1)
    type: str = Field(min_length=1)
    normalised_type: str = Field(min_length=1)
    length: int | None = Field(default=None, ge=1)
    nullable: bool
    default: str | None = None
    identity: bool
    generated: str | None = None
    generation_expression: str | None = None


class Constraint(SnapshotModel):
    """One table constraint.

    `columns` is empty for a check constraint that names no column.
    `referenced_table` and `referenced_columns` are set for foreign keys only.
    """

    name: str
    kind: str
    columns: list[str]
    referenced_table: str | None = None
    referenced_columns: list[str] = Field(default_factory=list)
    definition: str | None = None


class Index(SnapshotModel):
    """One index.

    For an expression index `columns` holds the plain columns only and
    `expression` holds the server's rendering of the expressions, so an index
    on `lower(email)` is not misreported as an index on `email`.
    """

    name: str
    columns: list[str]
    unique: bool
    method: str
    predicate: str | None = None
    valid: bool
    expression: str | None = None
    keys: list[str] | None = None
    included_columns: list[str] | None = None


class Table(SnapshotModel):
    """One table (ordinary or partitioned)."""

    schema_name: str = Field(alias="schema")
    name: str
    row_estimate: int | None = Field(default=None, ge=0)
    total_bytes: int = Field(ge=0)
    columns: list[Column]
    constraints: list[Constraint]
    indexes: list[Index]


class Sequence(SnapshotModel):
    """One sequence. Its current value is deliberately not captured."""

    schema_name: str = Field(alias="schema")
    name: str
    data_type: str
    start_value: int
    increment_by: int
    cycle: bool


class Snapshot(SnapshotModel):
    """A complete schema state."""

    schema_version: Literal[1] = 1
    dialect: str
    server_version: str
    captured_at: str
    database: str
    schemas: list[str]
    tables: list[Table]
    sequences: list[Sequence]
    extensions: list[str]


def sort_snapshot(snapshot: Snapshot) -> Snapshot:
    """Return the canonical ordering of a snapshot.

    Capturing already sorts, but sorting here as well means a snapshot built by
    hand (a fixture, a future importer) cannot produce unstable output.
    """
    tables = [
        table.model_copy(
            update={
                "columns": sorted(table.columns, key=lambda column: column.ordinal),
                "constraints": sorted(
                    table.constraints, key=lambda constraint: (constraint.kind, constraint.name)
                ),
                "indexes": sorted(table.indexes, key=lambda index: index.name),
            }
        )
        for table in snapshot.tables
    ]
    tables.sort(key=lambda table: (table.schema_name, table.name))

    sequences = sorted(
        snapshot.sequences, key=lambda sequence: (sequence.schema_name, sequence.name)
    )

    return snapshot.model_copy(
        update={
            "schemas": sorted(snapshot.schemas),
            "tables": tables,
            "sequences": sequences,
            "extensions": sorted(snapshot.extensions),
        }
    )


def to_payload(snapshot: Snapshot) -> dict[str, Any]:
    """Return the JSON-ready object, in canonical order."""
    return sort_snapshot(snapshot).model_dump(by_alias=True, mode="json")


def to_json(snapshot: Snapshot) -> str:
    """Serialise a snapshot. Same snapshot means same bytes, everywhere."""
    payload = to_payload(snapshot)
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def write_snapshot(path: Path, snapshot: Snapshot) -> None:
    """Write a snapshot atomically, so a failed run never leaves half a file."""
    text = to_json(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary)
        raise
