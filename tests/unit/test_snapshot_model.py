"""Snapshot model, ordering and byte-level determinism."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from schemasentry.snapshot import (
    Column,
    Constraint,
    Index,
    Sequence,
    Snapshot,
    Table,
    sort_snapshot,
    to_json,
    to_payload,
    write_snapshot,
)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "schema" / "snapshot-v1.schema.json"


def column(name: str, ordinal: int, **overrides: object) -> Column:
    data: dict[str, object] = {
        "name": name,
        "ordinal": ordinal,
        "type": "character varying(255)",
        "normalised_type": "varchar",
        "length": 255,
        "nullable": False,
        "default": None,
        "identity": False,
        "generated": None,
        "generation_expression": None,
    }
    data.update(overrides)
    return Column.model_validate(data)


def sample_snapshot() -> Snapshot:
    """Two tables, deliberately not in canonical order."""
    return Snapshot(
        dialect="postgres",
        server_version="16.4",
        captured_at="2026-11-13T10:00:00Z",
        database="app",
        schemas=["public"],
        tables=[
            Table(
                schema="public",
                name="users",
                row_estimate=None,
                total_bytes=8192,
                columns=[
                    column("email", 2),
                    column(
                        "id", 1, type="bigint", normalised_type="bigint", length=None, identity=True
                    ),
                ],
                constraints=[
                    Constraint(name="users_email_key", kind="unique", columns=["email"]),
                    Constraint(name="users_pkey", kind="primary_key", columns=["id"]),
                ],
                indexes=[
                    Index(
                        name="users_email_idx",
                        columns=["email"],
                        unique=False,
                        method="btree",
                        predicate=None,
                        valid=True,
                        expression=None,
                    )
                ],
            ),
            Table(
                schema="public",
                name="accounts",
                row_estimate=42,
                total_bytes=16384,
                columns=[column("id", 1)],
                constraints=[],
                indexes=[],
            ),
        ],
        sequences=[
            Sequence(
                schema="public",
                name="users_id_seq",
                data_type="bigint",
                start_value=1,
                increment_by=1,
                cycle=False,
            )
        ],
        extensions=["pgcrypto"],
    )


def test_tables_and_columns_are_in_canonical_order() -> None:
    payload = to_payload(sample_snapshot())

    assert [table["name"] for table in payload["tables"]] == ["accounts", "users"]
    users = payload["tables"][1]
    assert [entry["name"] for entry in users["columns"]] == ["id", "email"]
    assert [entry["name"] for entry in users["constraints"]] == [
        "users_pkey",
        "users_email_key",
    ]


def test_json_uses_wire_names_and_keeps_nulls() -> None:
    payload = to_payload(sample_snapshot())

    assert payload["schemaVersion"] == 1
    assert payload["capturedAt"] == "2026-11-13T10:00:00Z"
    users = payload["tables"][1]
    assert users["rowEstimate"] is None
    email = users["columns"][1]
    assert email["normalisedType"] == "varchar"
    assert email["length"] == 255
    assert email["default"] is None
    assert "generationExpression" in email


def test_same_snapshot_serialises_to_the_same_bytes() -> None:
    first = to_json(sample_snapshot())
    second = to_json(sample_snapshot())

    assert first == second
    assert first.endswith("\n")
    assert "\r" not in first


def test_sort_snapshot_accepts_already_sorted_input() -> None:
    snapshot = sample_snapshot()
    once = sort_snapshot(snapshot)
    twice = sort_snapshot(once)

    assert once == twice


def test_snapshot_matches_the_committed_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)

    jsonschema.validate(instance=to_payload(sample_snapshot()), schema=schema)


def test_unknown_type_is_preserved_verbatim() -> None:
    unknown = column("mood", 3, type="public.mood", normalised_type="mood", length=None)

    assert unknown.type == "public.mood"
    assert unknown.normalised_type == "mood"


def test_write_snapshot_is_atomic_and_ends_with_newline(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "snapshot.json"

    write_snapshot(target, sample_snapshot())

    text = target.read_text(encoding="utf-8")
    assert text == to_json(sample_snapshot())
    assert not list(target.parent.glob(".*.tmp"))


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValueError):
        Column.model_validate(
            {
                "name": "id",
                "ordinal": 1,
                "type": "integer",
                "normalised_type": "integer",
                "nullable": False,
                "identity": False,
                "surprise": True,
            }
        )
