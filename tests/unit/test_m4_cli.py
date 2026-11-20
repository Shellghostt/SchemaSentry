"""Real UTF-8 subprocess tests for M4 exits, offline precedence and metadata."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from schemasentry.cli import main
from schemasentry.config import DATABASE_URL_ENV

ROOT = Path(__file__).parents[2]
CORPUS = ROOT / "tests/corpus-m4"


def command(case, *args):
    folder = CORPUS / case
    return [
        "compare",
        "--baseline",
        str(folder / "before.json"),
        "--after",
        str(folder / "after.json"),
        "--migration",
        str(folder / "migration.sql"),
        "--format",
        "json",
        *args,
    ]


def process(args):
    environment = dict(os.environ)
    environment[DATABASE_URL_ENV] = "postgresql://private:DO_NOT_PRINT@127.0.0.1:1/unused"
    return subprocess.run(
        [sys.executable, "-m", "schemasentry", *args],
        capture_output=True,
        env=environment,
        timeout=20,
        check=False,
    )


@pytest.mark.parametrize(
    "threshold,expected", [("low", 1), ("medium", 1), ("high", 1), ("critical", 0)]
)
def test_complete_high_risk_thresholds_use_real_cli(threshold, expected):
    result = process(command("0060-check-immediate-validation", "--threshold", threshold))
    assert result.returncode == expected
    document = json.loads(result.stdout)
    assert document["analysisStatus"] == "complete" and document["overallRisk"] == "high"
    assert b"DO_NOT_PRINT" not in result.stdout + result.stderr
    assert result.stderr == b"" and b"\r" not in result.stdout


@pytest.mark.parametrize("threshold", ["low", "medium", "high", "critical"])
def test_critical_always_returns_two_and_incomplete_three(threshold):
    critical = process(command("0065-index-concurrent-in-transaction", "--threshold", threshold))
    incomplete = process(command("0062-check-validation-unknown", "--threshold", threshold))
    assert critical.returncode == 2 and json.loads(critical.stdout)["overallRisk"] == "critical"
    assert (
        incomplete.returncode == 3
        and json.loads(incomplete.stdout)["analysisStatus"] == "incomplete"
    )


def test_no_findings_offline_and_invalid_usage_codes():
    success = process(command("0064-index-concurrent-build", "--threshold", "low"))
    assert success.returncode == 0 and json.loads(success.stdout)["overallRisk"] is None
    for args in (
        ["--threshold", "unknown"],
        ["--format", "html"],
        ["--database", "postgresql://DO_NOT_PRINT@localhost/unused"],
        ["--captured-at", "2026-11-20T00:00:00Z"],
    ):
        invalid = process(["compare", "--baseline", "missing", "--after", "missing", *args])
        assert invalid.returncode == 4 and invalid.stdout == b""
        assert b"DO_NOT_PRINT" not in invalid.stderr
    blank = process(["compare", "--baseline", "missing", "--database", ""])
    assert blank.returncode == 4 and blank.stdout == b""


def test_metadata_commands_are_offline_with_database_environment(monkeypatch, capsys):
    monkeypatch.setenv(DATABASE_URL_ENV, "postgresql://DO_NOT_PRINT@127.0.0.1:1/unused")

    def forbidden(*args, **kwargs):
        raise AssertionError("metadata command attempted capture")

    monkeypatch.setattr("schemasentry.cli.capture_snapshot", forbidden)
    assert main(["rules", "--json"]) == 0
    rules = json.loads(capsys.readouterr().out)
    assert [rule["ruleId"] for rule in rules["rules"]] == [
        f"SS{number:03d}" for number in range(1, 11)
    ]
    assert main(["explain", "ss009"]) == 0
    assert "CONCURRENTLY" in capsys.readouterr().out
    assert main(["explain", "SS999"]) == 4


def test_malformed_input_and_output_alias_preserve_file(tmp_path):
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
    output = tmp_path / "report.json"
    output.write_bytes(b"previous")
    result = process(
        ["compare", "--baseline", str(invalid), "--after", str(invalid), "--output", str(output)]
    )
    assert result.returncode == 3 and result.stdout == b""
    assert output.read_bytes() == b"previous" and b"Traceback" not in result.stderr
    original = invalid.read_bytes()
    alias = process(
        ["compare", "--baseline", str(invalid), "--after", str(invalid), "--output", str(invalid)]
    )
    assert alias.returncode == 3 and invalid.read_bytes() == original


def test_successful_file_output_has_no_stdout_and_closed_stdout_is_tool_error(tmp_path):
    output = tmp_path / "report.json"
    args = command("0060-check-immediate-validation", "--output", str(output))
    result = process(args)
    assert result.returncode == 1 and result.stdout == b""
    assert json.loads(output.read_text("utf-8"))["overallRisk"] == "high"
    script = (
        "import os,sys; os.close(1); from schemasentry.cli import main; sys.exit(main("
        + repr(command("0060-check-immediate-validation"))
        + "))"
    )
    closed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, timeout=20, check=False
    )
    assert closed.returncode == 3 and b"Traceback" not in closed.stderr
