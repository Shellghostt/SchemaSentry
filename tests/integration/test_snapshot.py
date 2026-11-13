"""Integration tests against a real PostgreSQL server.

They are skipped unless SCHEMASENTRY_TEST_DATABASE_URL points at a disposable
database. The tool itself is read-only; this test is allowed to create a
throwaway schema to have something worth reading.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import jsonschema
import psycopg
import pytest

from schemasentry.cli import main
from schemasentry.db import connect_readonly
from schemasentry.errors import ToolError
from schemasentry.introspect import capture_snapshot
from schemasentry.snapshot import Column, Snapshot, Table, to_json

DSN = os.environ.get("SCHEMASENTRY_TEST_DATABASE_URL")
CAPTURED_AT = "2026-11-13T10:00:00Z"
SCHEMA_PATH = Path(__file__).resolve().parents[2] / "docs" / "schema" / "snapshot-v1.schema.json"

pytestmark = pytest.mark.skipif(
    not DSN,
    reason="set SCHEMASENTRY_TEST_DATABASE_URL to run integration tests",
)


def _execute(statements: list[str]) -> None:
    assert DSN is not None
    with (
        psycopg.connect(DSN, autocommit=True) as connection,
        connection.cursor() as cursor,
    ):
        for statement in statements:
            cursor.execute(statement)


@pytest.fixture(scope="module")
def schema_name() -> Iterator[str]:
    name = f"ss_it_{uuid.uuid4().hex[:8]}"
    _execute(
        [
            f"CREATE SCHEMA {name}",
            f"CREATE TYPE {name}.mood AS ENUM ('happy', 'sad', 'neutral')",
            f"""
            CREATE TABLE {name}.accounts (
                id bigserial PRIMARY KEY,
                email varchar(255) NOT NULL UNIQUE,
                created_at timestamptz NOT NULL DEFAULT now()
            )
            """,
            f"""
            CREATE TABLE {name}.orders (
                id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                account_id bigint NOT NULL REFERENCES {name}.accounts(id),
                status text NOT NULL DEFAULT 'new',
                mood {name}.mood,
                total numeric(12,2) NOT NULL DEFAULT 0,
                doubled numeric(12,2) GENERATED ALWAYS AS (total * 2) STORED,
                note varchar(100),
                CONSTRAINT orders_status_check CHECK (status <> '')
            )
            """,
            f"""
            CREATE UNIQUE INDEX orders_status_account_idx
                ON {name}.orders (account_id) WHERE status = 'new'
            """,
            f"CREATE INDEX orders_lower_note_idx ON {name}.orders (lower(note))",
            f"CREATE TABLE {name}.never_analysed (id integer)",
            f"CREATE TABLE {name}.legacy (id serial PRIMARY KEY)",
        ]
    )
    try:
        yield name
    finally:
        _execute([f"DROP SCHEMA {name} CASCADE"])


@pytest.fixture(scope="module")
def snapshot(schema_name: str) -> Snapshot:
    assert DSN is not None
    return capture_snapshot(DSN, schemas=[schema_name], captured_at=CAPTURED_AT)


def _table(snapshot: Snapshot, name: str) -> Table:
    for table in snapshot.tables:
        if table.name == name:
            return table
    raise AssertionError(
        f"table {name} was not captured: {[table.name for table in snapshot.tables]}"
    )


def _column(snapshot: Snapshot, table: str, column: str) -> Column:
    for entry in _table(snapshot, table).columns:
        if entry.name == column:
            return entry
    raise AssertionError(f"column {table}.{column} was not captured")


def test_captures_every_table_in_the_schema(snapshot: Snapshot, schema_name: str) -> None:
    assert snapshot.schemas == [schema_name]
    assert snapshot.dialect == "postgres"
    assert snapshot.server_version
    assert snapshot.database
    assert {table.name for table in snapshot.tables} == {
        "accounts",
        "orders",
        "never_analysed",
        "legacy",
    }


def test_columns_keep_types_lengths_and_identity(snapshot: Snapshot, schema_name: str) -> None:
    note = _column(snapshot, "orders", "note")
    assert note.type == "character varying(100)"
    assert note.normalised_type == "varchar"
    assert note.length == 100
    assert note.nullable is True

    email = _column(snapshot, "accounts", "email")
    assert email.length == 255
    assert email.nullable is False

    identity = _column(snapshot, "orders", "id")
    assert identity.identity is True
    assert identity.default is None
    assert identity.type == "integer"

    serial = _column(snapshot, "accounts", "id")
    assert serial.identity is False
    assert serial.default is not None
    assert "nextval" in (serial.default or "")

    total = _column(snapshot, "orders", "total")
    assert total.type == "numeric(12,2)"
    assert total.normalised_type == "numeric"


def test_unknown_types_are_preserved_verbatim(snapshot: Snapshot, schema_name: str) -> None:
    mood = _column(snapshot, "orders", "mood")

    assert mood.type == f"{schema_name}.mood"
    assert mood.normalised_type == "mood"
    assert mood.length is None


def test_generated_columns_are_distinguished_from_defaults(snapshot: Snapshot) -> None:
    doubled = _column(snapshot, "orders", "doubled")

    assert doubled.generated == "stored"
    assert doubled.default is None
    assert doubled.generation_expression is not None
    assert "total" in doubled.generation_expression


def test_constraints_are_captured_with_foreign_key_targets(
    snapshot: Snapshot, schema_name: str
) -> None:
    constraints = {
        constraint.kind: constraint for constraint in _table(snapshot, "orders").constraints
    }

    assert constraints["primary_key"].columns == ["id"]
    assert constraints["check"].columns == ["status"]
    assert constraints["check"].name == "orders_status_check"

    foreign_key = constraints["foreign_key"]
    assert foreign_key.columns == ["account_id"]
    assert foreign_key.referenced_table == f"{schema_name}.accounts"
    assert foreign_key.referenced_columns == ["id"]


def test_indexes_distinguish_partial_and_expression_indexes(snapshot: Snapshot) -> None:
    indexes = {index.name: index for index in _table(snapshot, "orders").indexes}

    partial = indexes["orders_status_account_idx"]
    assert partial.unique is True
    assert partial.method == "btree"
    assert partial.predicate is not None
    assert "status" in partial.predicate
    assert partial.expression is None
    assert partial.columns == ["account_id"]

    expression = indexes["orders_lower_note_idx"]
    assert expression.columns == []
    assert expression.expression is not None
    assert "lower" in expression.expression


def test_row_estimate_is_null_for_an_unanalysed_table(snapshot: Snapshot) -> None:
    assert _table(snapshot, "never_analysed").row_estimate is None
    assert _table(snapshot, "accounts").total_bytes >= 0


def test_analysed_empty_table_reports_zero_not_null(schema_name: str) -> None:
    # The difference that matters: an analysed table with no rows is 0, a table
    # nobody ever analysed is unknown. PostgreSQL 13 reports both as 0 in
    # pg_class, so the snapshot also looks at the statistics.
    #
    # On PostgreSQL 13 the statistics collector publishes the result of ANALYZE
    # a moment later, so the snapshot is retried until the value appears.
    assert DSN is not None
    _execute([f"ANALYZE {schema_name}.never_analysed"])

    deadline = time.monotonic() + 10
    estimate: int | None = None
    while time.monotonic() < deadline:
        analysed = capture_snapshot(DSN, schemas=[schema_name], captured_at=CAPTURED_AT)
        estimate = _table(analysed, "never_analysed").row_estimate
        if estimate is not None:
            break
        time.sleep(0.25)

    assert estimate == 0


def test_sequences_are_captured(snapshot: Snapshot) -> None:
    sequences = {sequence.name: sequence for sequence in snapshot.sequences}

    assert "legacy_id_seq" in sequences
    # `serial` is an integer sequence; `bigserial` would be bigint.
    assert sequences["legacy_id_seq"].data_type == "integer"
    assert sequences["legacy_id_seq"].increment_by == 1
    assert sequences["legacy_id_seq"].cycle is False


def test_two_captures_of_an_unchanged_database_are_byte_identical(
    schema_name: str,
) -> None:
    assert DSN is not None
    first = capture_snapshot(DSN, schemas=[schema_name], captured_at=CAPTURED_AT)
    second = capture_snapshot(DSN, schemas=[schema_name], captured_at=CAPTURED_AT)

    assert to_json(first) == to_json(second)


def test_captured_snapshot_matches_the_committed_schema(snapshot: Snapshot) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(instance=json.loads(to_json(snapshot)), schema=schema)


def test_connection_is_read_only_and_timed() -> None:
    assert DSN is not None
    with connect_readonly(DSN) as connection:
        row = connection.execute("SHOW transaction_read_only").fetchone()
        assert row == {"transaction_read_only": "on"}

        timeout = connection.execute("SHOW statement_timeout").fetchone()
        assert timeout == {"statement_timeout": "5s"}

        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            connection.execute("CREATE TABLE public.must_not_exist (id integer)")


def test_missing_schema_is_a_tool_error() -> None:
    assert DSN is not None
    with pytest.raises(ToolError):
        capture_snapshot(DSN, schemas=["ss_it_does_not_exist"])


def test_snapshot_command_writes_a_file(
    schema_name: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert DSN is not None
    target = tmp_path / "snapshot.json"

    code = main(
        [
            "snapshot",
            "--database",
            DSN,
            "--schema",
            schema_name,
            "--captured-at",
            CAPTURED_AT,
            "--output",
            str(target),
        ]
    )

    assert code == 0
    assert "wrote snapshot" in capsys.readouterr().err

    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["schemaVersion"] == 1
    assert document["capturedAt"] == CAPTURED_AT
    assert {table["name"] for table in document["tables"]} >= {"orders", "accounts"}
