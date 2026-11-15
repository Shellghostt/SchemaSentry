"""Reviewed M3 corpus and evidence contracts; no migration execution."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import Any

import psycopg
import pytest
from schemasentry.classification import classify
from schemasentry.hints import load_hints
from schemasentry.migration import MAX_SQL_BYTES, load_migration, parse_migration

from schemasentry.diff import compare, comparison_json, load_snapshot
from schemasentry.errors import ToolError
from schemasentry.rules import rule_metadata
from schemasentry.snapshot import Snapshot, to_json

CORPUS = Path(__file__).resolve().parents[1] / "corpus"
CASES = sorted(CORPUS.glob("*/expected.json"))


def read_case(path: Path) -> tuple[Snapshot, Snapshot, dict[str, Any]]:
    before = load_snapshot(path.parent / "before.json")
    after = load_snapshot(path.parent / "after.json")
    expected = json.loads(path.read_text(encoding="utf-8"))
    return before, after, expected


def project_findings(result: Any, expected: dict[str, Any]) -> list[dict[str, Any]]:
    fields = {"schema", "table", "object", "kind", "baseSeverity", "confidence"}
    selected = [f for f in result.findings if f.rule_id == expected["ruleId"]]
    projected = []
    for finding in selected:
        payload = finding.model_dump(by_alias=True, mode="json")
        item = {key: payload[key] for key in fields}
        if any("effects" in f for f in expected["findings"]):
            item["effects"] = payload["effects"]
        projected.append(item)
    return sorted(projected, key=lambda f: (f["schema"], f["table"], f["object"], f["kind"]))


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.parent.name)
def test_reviewed_m3_corpus(path: Path) -> None:
    before, after, expected = read_case(path)
    migration = load_migration(path.parent / "migration.sql")
    assert [s.status for s in migration.statements] == expected["statementStatuses"]
    before_bytes, after_bytes = to_json(before), to_json(after)
    structural_bytes = comparison_json(compare(before, after))
    hint_file = path.parent / "hints.json"
    if expected["hintError"]:
        with pytest.raises((ValueError, ToolError), match=r"rename|hint"):
            classify(before, after, migration=migration, hints=load_hints(hint_file))
        return
    hints = load_hints(hint_file) if hint_file.exists() else None
    result = classify(before, after, migration=migration, hints=hints)
    assert project_findings(result, expected) == expected["findings"]
    assert to_json(before) == before_bytes
    assert to_json(after) == after_bytes
    assert comparison_json(compare(before, after)) == structural_bytes
    assert (
        result.model_dump_json()
        == classify(before, after, migration=migration, hints=hints).model_dump_json()
    )
    assert not {"risk", "exitCode", "estimatedSeconds"} & result.model_dump(by_alias=True).keys()


def test_every_rule_has_reviewed_positive_negative_edge_cases() -> None:
    coverage: dict[str, set[str]] = {}
    for path in CASES:
        case = json.loads(path.read_text(encoding="utf-8"))
        coverage.setdefault(case["ruleId"], set()).add(case["category"])
        assert (path.parent / "before.sql").is_file()
        assert (path.parent / "migration.sql").is_file()
        assert (path.parent / "notes.md").is_file()
    ids = {rule.rule_id for rule in rule_metadata()}
    assert ids == {f"SS{i:03d}" for i in range(1, 8)}
    assert set(coverage) == ids
    assert len(CASES) >= 21
    for categories in coverage.values():
        assert {"positive", "negative", "edge"} <= categories


def test_sql_order_locations_quotes_comments_and_wrappers() -> None:
    text = (
        "-- comment with ;\nBEGIN;\n"
        'ALTER TABLE "Odd.Schema"."Things" ALTER COLUMN "A;B" TYPE bigint;\n'
        "COMMIT;\nSELECT 'not;a;split';"
    )
    parsed = parse_migration(text)
    assert [s.status for s in parsed.statements] == [
        "supported",
        "supported",
        "supported",
        "unsupported",
    ]
    operation = parsed.statements[1].operations[0]
    assert operation.schema_name == "Odd.Schema"
    assert operation.table == "Things"
    assert operation.column == "A;B"
    assert parsed.statements[1].location.line == 3
    assert parsed.statements[1].location.column == 1
    assert (
        text[parsed.statements[1].location.start : parsed.statements[1].location.start + 11]
        == "ALTER TABLE"
    )


def test_unsupported_and_invalid_sql_are_visible_without_logging(caplog: Any, capsys: Any) -> None:
    token = "synthetic-private-value"
    parsed = parse_migration(
        f"DO $$ BEGIN PERFORM '{token}'; END $$; ALTER TABLE public.items ALTER COLUMN body TYPE;"
    )
    assert parsed.errors or any(s.status == "parse_error" for s in parsed.statements)
    assert any(s.status == "unsupported" for s in parsed.statements)
    assert token not in caplog.text
    output = capsys.readouterr()
    assert token not in output.out + output.err


def test_partially_supported_alter_is_not_silently_accepted() -> None:
    parsed = parse_migration(
        "ALTER TABLE public.items ADD COLUMN extra text, ADD CONSTRAINT c CHECK (extra <> '');"
    )
    assert parsed.statements[0].status == "unsupported"
    assert parsed.statements[0].operations == ()


@pytest.mark.parametrize(
    "text",
    [
        " " * (MAX_SQL_BYTES + 1),
        "\u20ac" * (MAX_SQL_BYTES // 3 + 1),
        "SELECT 1;" * 129,
        "SELECT " * 20_001,
        "SELECT " + "(" * 65 + "1" + ")" * 65,
    ],
    ids=["bytes", "utf8-bytes", "statements", "tokens", "depth"],
)
def test_parser_resource_limits_are_explicit(text: str) -> None:
    parsed = parse_migration(text)
    assert parsed.errors


def test_missing_migration_and_unqualified_targets_are_not_guessed() -> None:
    before, after, _ = read_case(CASES[1])
    result = classify(before, after)
    assert any(n.kind == "migration_evidence_missing" for n in result.notices)
    unqualified = parse_migration("ALTER TABLE items ALTER COLUMN body SET DEFAULT 'new';")
    result = classify(before, after, migration=unqualified)
    assert any(n.kind == "unresolved_statement_target" for n in result.notices)
    assert not any(f.rule_id == "SS005" for f in result.findings)
    bound = classify(before, after, migration=unqualified, default_schema=before.schemas[0])
    assert any(f.rule_id == "SS005" for f in bound.findings)


@pytest.mark.parametrize(
    "payload",
    [
        '{"schemaVersion":true,"renames":[]}',
        '{"schemaVersion":1,"schemaVersion":1,"renames":[]}',
        '{"schemaVersion":1,"renames":[],"unknown":1}',
        '{"schemaVersion":1,"renames":[]} {}',
        '{"renames":[]}',
        '{"schemaVersion":2,"renames":[]}',
    ],
)
def test_hint_file_is_strict_versioned_json(tmp_path: Path, payload: str) -> None:
    file = tmp_path / "hints.json"
    file.write_text(payload, encoding="utf-8")
    with pytest.raises((ValueError, ToolError)):
        load_hints(file)


def test_hint_file_read_is_bounded(tmp_path: Path) -> None:
    file = tmp_path / "hints.json"
    file.write_bytes(b" " * (64 * 1024 + 1))
    with pytest.raises((ValueError, ToolError), match="64 KiB"):
        load_hints(file)


def test_hints_cannot_hide_absent_endpoints_or_cycles(tmp_path: Path) -> None:
    before, after, _ = read_case(next(p for p in CASES if "explicit-column-rename" in str(p)))
    schema = before.schemas[0]
    for renames in [
        [{"schema": schema, "table": "items", "from": "absent", "to": "message"}],
        [
            {"schema": schema, "table": "items", "from": "body", "to": "message"},
            {"schema": schema, "table": "items", "from": "message", "to": "body"},
        ],
    ]:
        file = tmp_path / "hints.json"
        file.write_text(json.dumps({"schemaVersion": 1, "renames": renames}), encoding="utf-8")
        with pytest.raises((ValueError, ToolError), match=r"rename|hint"):
            classify(before, after, hints=load_hints(file))


def test_shuffled_inputs_and_hinted_attribute_changes() -> None:
    path = next(p for p in CASES if "rename-and-type-change" in str(p))
    before, after, _ = read_case(path)
    hints = load_hints(path.parent / "hints.json")
    migration = load_migration(path.parent / "migration.sql")
    baseline = classify(before, after, hints=hints, migration=migration)
    shuffled_before = copy.deepcopy(before)
    shuffled_after = copy.deepcopy(after)
    shuffled_before.tables.reverse()
    shuffled_after.tables.reverse()
    for snapshot in (shuffled_before, shuffled_after):
        for table in snapshot.tables:
            table.columns.reverse()
            table.constraints.reverse()
            table.indexes.reverse()
    assert (
        baseline.model_dump_json()
        == classify(
            shuffled_before, shuffled_after, hints=hints, migration=migration
        ).model_dump_json()
    )
    assert any(f.rule_id == "SS002" for f in baseline.findings)
    assert not any(f.rule_id == "SS001" for f in baseline.findings)
    structural = compare(before, after)
    assert {c.kind for c in structural.changes} == {"column_added", "column_removed"}


def test_classifier_never_connects_or_executes_migration(monkeypatch: Any) -> None:
    def denied(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("classification performed database I/O")

    monkeypatch.setattr(psycopg, "connect", denied)
    before, after, _ = read_case(CASES[0])
    result = classify(before, after, migration=parse_migration("DROP DATABASE production;"))
    assert result.findings
    assert any(n.kind == "unanalysable_statement" for n in result.notices)


def test_classifier_modules_do_not_import_database_or_process_apis() -> None:
    package = Path(__file__).resolve().parents[2] / "src" / "schemasentry"
    files = [package / "classification.py", *(package / "rules").glob("*.py")]
    forbidden = {
        "psycopg",
        "subprocess",
        "socket",
        "os",
        "schemasentry.db",
        "schemasentry.introspect",
    }
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name not in forbidden for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                assert node.module not in forbidden
