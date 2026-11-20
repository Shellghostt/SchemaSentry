"""Verify installed M3 oracles, M4 CLI reports, metadata and structural fixture JSON offline."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import schemasentry
from schemasentry.classification import classify
from schemasentry.diff import load_snapshot
from schemasentry.errors import ToolError
from schemasentry.hints import load_hints
from schemasentry.migration import load_migration


def command(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    environment = dict(os.environ)
    environment["SCHEMASENTRY_DATABASE_URL"] = (
        "postgresql://private:DO_NOT_PRINT@127.0.0.1:1/unused"
    )
    result = subprocess.run(
        [sys.executable, "-m", "schemasentry", *arguments],
        capture_output=True,
        env=environment,
        timeout=20,
        check=False,
    )
    assert b"DO_NOT_PRINT" not in result.stdout + result.stderr
    assert b"Traceback" not in result.stderr and b"\r" not in result.stdout
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixtures", type=Path, default=Path(__file__).resolve().parent.parent / "tests"
    )
    args = parser.parse_args()
    m3_cases = hint_errors = 0
    for oracle in sorted((args.fixtures / "corpus").glob("*/expected.json")):
        folder = oracle.parent
        expected = json.loads(oracle.read_text("utf-8"))
        migration = load_migration(folder / "migration.sql")
        assert [statement.status for statement in migration.statements] == expected[
            "statementStatuses"
        ]
        before, after = load_snapshot(folder / "before.json"), load_snapshot(folder / "after.json")
        hint_file = folder / "hints.json"
        try:
            hints = load_hints(hint_file) if hint_file.is_file() else None
            result = classify(before, after, migration=migration, hints=hints)
        except (ValueError, ToolError):
            assert expected["hintError"], folder.name
            hint_errors += 1
        else:
            assert not expected["hintError"], folder.name
            fields = {"schema", "table", "object", "kind", "baseSeverity", "confidence"}
            if any("effects" in item for item in expected["findings"]):
                fields.add("effects")
            findings = [
                {key: finding.model_dump(by_alias=True, mode="json")[key] for key in fields}
                for finding in result.findings
                if finding.rule_id == expected["ruleId"]
            ]
            findings.sort(
                key=lambda item: (item["schema"], item["table"], item["object"], item["kind"])
            )
            assert findings == expected["findings"], folder.name
        m3_cases += 1
    m4_cases = 0
    for oracle in sorted((args.fixtures / "corpus-m4").glob("*/expected.json")):
        folder = oracle.parent
        expected = json.loads(oracle.read_text("utf-8"))
        result = command(
            [
                "compare",
                "--baseline",
                str(folder / "before.json"),
                "--after",
                str(folder / "after.json"),
                "--migration",
                str(folder / "migration.sql"),
                "--format",
                "json",
            ]
        )
        assert result.returncode == expected["exitHigh"], folder.name
        report = json.loads(result.stdout)
        assert result.stderr == b""
        assert report["analysisStatus"] == expected["analysisStatus"]
        assert report["overallRisk"] == expected["overallRisk"]
        keys = {"ruleId", "kind", "baseSeverity", "finalRisk", "confidence"}
        assert [{key: finding[key] for key in keys} for finding in report["findings"]] == expected[
            "findings"
        ]
        assert all(finding["estimatedSeconds"] is None for finding in report["findings"])
        m4_cases += 1
    structural = 0
    for oracle in sorted((args.fixtures / "fixtures").glob("*/expected.json")):
        folder = oracle.parent
        result = command(
            [
                "diff",
                "--before",
                str(folder / "before.json"),
                "--after",
                str(folder / "after.json"),
            ]
        )
        assert result.returncode == 0 and result.stderr == b"", folder.name
        assert json.loads(result.stdout) == json.loads(oracle.read_text("utf-8")), folder.name
        structural += 1
    rules, explain = command(["rules", "--json"]), command(["explain", "SS009"])
    assert rules.returncode == explain.returncode == 0
    assert len(json.loads(rules.stdout)["rules"]) == 10 and b"CONCURRENTLY" in explain.stdout
    assert m3_cases == 59 and hint_errors == 2 and m4_cases >= 9 and structural == 30
    print(
        json.dumps(
            {
                "python": sys.version.split()[0],
                "package": schemasentry.__file__,
                "m3Cases": m3_cases,
                "expectedHintErrors": hint_errors,
                "m4CliCases": m4_cases,
                "structuralCliFixtures": structural,
                "metadataCommands": 2,
            }
        )
    )


if __name__ == "__main__":
    main()
