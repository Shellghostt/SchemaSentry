"""Golden structural-change sets, command contracts and scaling checks."""

import copy
import json
import time
from pathlib import Path

import pytest

from schemasentry.cli import main
from schemasentry.diff import compare, comparison_json, load_snapshot
from schemasentry.errors import ToolError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
CASES = sorted(p for p in FIXTURES.iterdir() if p.is_dir() and (p / "before.json").exists())


@pytest.mark.parametrize("case", CASES, ids=lambda path: path.name)
def test_fixture_pair(case: Path) -> None:
    before, after = load_snapshot(case / "before.json"), load_snapshot(case / "after.json")
    actual = comparison_json(compare(before, after))
    assert json.loads(actual) == json.loads((case / "expected.json").read_text())
    assert actual == comparison_json(compare(before, after))
    assert actual.endswith("\n")


def test_fixture_minimum() -> None:
    assert len(CASES) >= 20


def test_cli_changes_exit_zero_without_risk_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    case = FIXTURES / "05-column-removed"
    assert (
        main(["diff", "--before", str(case / "before.json"), "--after", str(case / "after.json")])
        == 0
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["changes"][0]["kind"] == "column_removed"


@pytest.mark.parametrize("mutation", ["version", "missing_version", "duplicate", "dialect"])
def test_invalid_snapshot_rejected(tmp_path: Path, mutation: str) -> None:
    payload = json.loads((CASES[0] / "before.json").read_text())
    if mutation == "version":
        payload["schemaVersion"] = 999
    elif mutation == "missing_version":
        del payload["schemaVersion"]
    elif mutation == "duplicate":
        payload["tables"].append(copy.deepcopy(payload["tables"][0]))
    else:
        payload["dialect"] = "mysql"
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ToolError):
        load_snapshot(path)


def test_file_errors_use_tool_exit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["diff", "--before", str(tmp_path / "absent"), "--after", "absent"]) == 3
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize("version", [True, 1.0, "1"])
def test_version_must_be_an_integer(tmp_path: Path, version: object) -> None:
    payload = json.loads((CASES[0] / "before.json").read_text())
    payload["schemaVersion"] = version
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ToolError):
        load_snapshot(path)


def test_duplicate_json_keys_are_not_silently_accepted(tmp_path: Path) -> None:
    raw = (CASES[0] / "before.json").read_text()
    path = tmp_path / "snapshot.json"
    path.write_text(raw.replace('"schemaVersion": 1', '"schemaVersion": 999, "schemaVersion": 1'))
    with pytest.raises(ToolError):
        load_snapshot(path)


def test_snapshot_order_does_not_change_diff_bytes() -> None:
    case = FIXTURES / "30-schema-qualified-sort"
    before, after = load_snapshot(case / "before.json"), load_snapshot(case / "after.json")
    expected = comparison_json(compare(before, after))
    for snapshot in (before, after):
        snapshot.tables.reverse()
        for table in snapshot.tables:
            table.columns.reverse()
            table.constraints.reverse()
            table.indexes.reverse()
    assert comparison_json(compare(before, after)) == expected


def test_legacy_snapshot_warns_about_missing_metadata() -> None:
    snapshot = load_snapshot(CASES[0] / "before.json")
    old = snapshot.model_copy(deep=True)
    old.tables[0].constraints[0] = (
        old.tables[0].constraints[0].model_copy(update={"definition": None})
    )
    result = compare(old, old)
    assert result.changes == []
    assert "Legacy constraint" in result.warnings[0]


def test_500_table_comparison_under_ten_seconds() -> None:
    snapshot = load_snapshot(CASES[0] / "before.json")
    tables = [
        snapshot.tables[0].model_copy(update={"name": f"table_{i:04d}"}, deep=True)
        for i in range(500)
    ]
    before = snapshot.model_copy(update={"tables": tables})
    after = before.model_copy(deep=True)
    after.tables[-1].columns[0] = after.tables[-1].columns[0].model_copy(update={"nullable": True})
    start = time.perf_counter()
    result = compare(before, after)
    elapsed = time.perf_counter() - start
    assert len(result.changes) == 1
    assert elapsed < 10
    print(f"500 tables: {elapsed:.6f} seconds")
