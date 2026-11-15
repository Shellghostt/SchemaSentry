"""Adversarial evidence must remain bounded, immutable and explicitly uncertain."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from schemasentry.classification import classify
from schemasentry.diff import compare, load_snapshot
from schemasentry.errors import ToolError
from schemasentry.hints import load_hints
from schemasentry.migration import MAX_SQL_BYTES, load_migration, parse_migration

CORPUS = Path(__file__).resolve().parents[1] / "corpus"


def test_finding_and_nested_result_are_frozen() -> None:
    case = CORPUS / "0001-drop-column"
    result = classify(
        load_snapshot(case / "before.json"),
        load_snapshot(case / "after.json"),
        migration=load_migration(case / "migration.sql"),
    )
    assert isinstance(result.findings, tuple) and isinstance(result.notices, tuple)
    assert isinstance(result.findings[0].evidence, tuple)
    with pytest.raises(ValidationError, match="frozen_instance"):
        result.findings = ()
    with pytest.raises(ValidationError, match="frozen_instance"):
        result.findings[0].base_severity = "low"
    assert "ruleId" in json.loads(result.model_dump_json())["findings"][0]


@pytest.mark.parametrize("text", ["VACUUM " + "x " * 20_001, "DO " + "(" * 65 + "1" + ")" * 65])
def test_command_fallback_cannot_bypass_resource_limits(text: str) -> None:
    result = parse_migration(text)
    assert result.errors and result.errors[0].kind == "limit_exceeded"
    assert result.statements == ()


def test_migration_byte_and_statement_boundaries(tmp_path: Path) -> None:
    text = "SELECT 1;\n--" + "x" * (MAX_SQL_BYTES - 12)
    assert len(text.encode("utf-8")) == MAX_SQL_BYTES
    file = tmp_path / "migration.sql"
    file.write_bytes(text.encode("utf-8"))
    result = load_migration(file)
    assert not result.errors and result.text == text
    assert len(parse_migration("SELECT 1;" * 128).statements) == 128
    file.write_bytes(b"x" * (MAX_SQL_BYTES + 1))
    assert load_migration(file).errors[0].kind == "limit_exceeded"
    file.write_bytes(b"\xff")
    assert load_migration(file).errors[0].kind == "invalid_utf8"
    assert parse_migration("\ud800").errors[0].kind == "invalid_utf8"


def test_sql_strings_dollar_quotes_and_nested_comments_preserve_statement_slices() -> None:
    text = (
        "/* outer /* nested ; */ comment */\n"
        "BEGIN;\nDO $body$ BEGIN PERFORM 'x;y'; END $body$;\n"
        "ALTER TABLE public.items ALTER COLUMN body SET DEFAULT E'a\\';b';\nCOMMIT;"
    )
    parsed = parse_migration(text)
    assert [s.status for s in parsed.statements] == [
        "supported",
        "unsupported",
        "supported",
        "supported",
    ]
    assert parsed.text == text
    for statement in parsed.statements:
        assert statement.text == text[statement.location.start : statement.location.end]
    assert parsed.statements[2].location.line == 4


def test_unquoted_identifiers_fold_ascii_without_changing_unicode() -> None:
    statement = parse_migration(
        "ALTER TABLE PUBLIC.ÄItems ALTER COLUMN ÄBody SET DEFAULT 'new';"
    ).statements[0]
    operation = statement.operations[0]
    assert operation.schema_name == "public"
    assert operation.table == "Äitems" and operation.column == "Äbody"


@pytest.mark.parametrize(
    "text",
    [
        "ALTER TABLE public.items ADD COLUMN x integer GENERATED ALWAYS AS IDENTITY;",
        "ALTER TABLE public.items ADD COLUMN x integer GENERATED ALWAYS AS (1 + 2) STORED;",
        "ALTER TABLE public.items ADD COLUMN x text, ALTER COLUMN body SET STATISTICS 50;",
        "ALTER TABLE public.items ALTER COLUMN body TYPE text COLLATE custom_collation;",
    ],
)
def test_unsupported_alter_actions_never_keep_partial_operations(text: str) -> None:
    statement = parse_migration(text).statements[0]
    assert statement.status != "supported" and statement.operations == ()


@pytest.mark.parametrize("version", ["14.0", "17.0", "18.0", "unknown", "15.10"])
def test_unconfirmed_versions_never_claim_no_rewrite(version: str) -> None:
    case = CORPUS / "0005-varchar-widen"
    before = load_snapshot(case / "before.json")
    after = load_snapshot(case / "after.json").model_copy(update={"server_version": version})
    result = classify(before, after, migration=load_migration(case / "migration.sql"))
    assert any(f.rule_id == "SS002" and f.confidence == "low" for f in result.findings)
    assert all(f.effects is None or f.effects.rewrite == "unknown" for f in result.findings)


def test_unsupported_intervening_sql_prevents_a_widening_negative() -> None:
    case = CORPUS / "0005-varchar-widen"
    before, after = load_snapshot(case / "before.json"), load_snapshot(case / "after.json")
    text = (case / "migration.sql").read_text() + "\nDO $$ BEGIN PERFORM 1; END $$;"
    result = classify(before, after, migration=parse_migration(text))
    assert any(f.rule_id == "SS002" and f.confidence == "low" for f in result.findings)
    assert any(n.kind == "unanalysable_statement" for n in result.notices)


def test_declared_default_does_not_override_a_different_observed_function() -> None:
    case = CORPUS / "0047-unknown-user-function"
    before, after = load_snapshot(case / "before.json"), load_snapshot(case / "after.json")
    text = (
        f"ALTER TABLE {before.schemas[0]}.items ALTER COLUMN value SET DEFAULT pg_catalog.random();"
    )
    result = classify(before, after, migration=parse_migration(text))
    finding = next(f for f in result.findings if f.rule_id == "SS007")
    assert finding.kind == "default_volatility_unknown" and finding.confidence == "low"
    assert any(n.kind == "statement_snapshot_evidence_unconfirmed" for n in result.notices)


def test_large_observed_expression_does_not_escape_as_a_recursion_failure() -> None:
    case = CORPUS / "0047-unknown-user-function"
    before, after = load_snapshot(case / "before.json"), load_snapshot(case / "after.json")
    table = after.tables[0]
    columns = [
        c.model_copy(update={"default": "1" + " + 1" * 1500}) if c.name == "value" else c
        for c in table.columns
    ]
    after = after.model_copy(update={"tables": [table.model_copy(update={"columns": columns})]})
    text = f"ALTER TABLE {before.schemas[0]}.items ALTER COLUMN value SET DEFAULT 1;"
    result = classify(before, after, migration=parse_migration(text))
    assert any(f.kind == "default_volatility_unknown" for f in result.findings)
    assert any(n.kind == "statement_snapshot_evidence_unconfirmed" for n in result.notices)


def test_sql_rename_is_not_an_implicit_hint() -> None:
    case = CORPUS / "0040-explicit-column-rename"
    before, after = load_snapshot(case / "before.json"), load_snapshot(case / "after.json")
    result = classify(before, after, migration=load_migration(case / "migration.sql"))
    assert any(f.rule_id == "SS001" and f.object == "body" for f in result.findings)
    assert not any(f.rule_id == "SS006" for f in result.findings)
    assert {c.kind for c in compare(before, after).changes} == {"column_removed", "column_added"}


def test_multiple_hint_and_table_order_is_deterministic(tmp_path: Path) -> None:
    case = CORPUS / "0040-explicit-column-rename"
    before, after = load_snapshot(case / "before.json"), load_snapshot(case / "after.json")
    before = before.model_copy(
        update={"tables": [*before.tables, before.tables[0].model_copy(update={"name": "zitems"})]}
    )
    after = after.model_copy(
        update={"tables": [*after.tables, after.tables[0].model_copy(update={"name": "zitems"})]}
    )
    schema = before.schemas[0]
    renames = [
        {"schema": schema, "table": name, "from": "body", "to": "message"}
        for name in ("items", "zitems")
    ]
    file = tmp_path / "hints.json"
    file.write_text(json.dumps({"schemaVersion": 1, "renames": renames}))
    original = classify(before, after, hints=load_hints(file))
    shuffled_before, shuffled_after = copy.deepcopy(before), copy.deepcopy(after)
    for snapshot in (shuffled_before, shuffled_after):
        snapshot.tables.reverse()
        for table in snapshot.tables:
            table.columns.reverse()
    file.write_text(json.dumps({"schemaVersion": 1, "renames": list(reversed(renames))}))
    assert (
        original.model_dump_json()
        == classify(shuffled_before, shuffled_after, hints=load_hints(file)).model_dump_json()
    )
    assert len([f for f in original.findings if f.rule_id == "SS006"]) == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 1, "renames": []},
        {
            "schemaVersion": 1,
            "renames": [{"schema_name": "public", "table": "x", "from": "a", "to": "b"}],
        },
        {"schemaVersion": 1, "renames": [{"schema": "public", "table": "x", "from": 1, "to": "b"}]},
        {
            "schemaVersion": 1,
            "renames": [{"schema": "public", "table": "x", "from": "a", "to": "b"}] * 129,
        },
    ],
)
def test_python_aliases_and_excessive_hint_mappings_are_rejected(
    tmp_path: Path, payload: Any
) -> None:
    file = tmp_path / "hints.json"
    file.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ToolError):
        load_hints(file)
