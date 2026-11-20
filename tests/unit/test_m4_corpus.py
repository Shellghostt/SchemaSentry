"""Reviewed M4 policy/evidence oracles, committed before new rule implementation."""

import json
from pathlib import Path

import pytest

from schemasentry.assessment import assess, report_exit
from schemasentry.diff import load_snapshot
from schemasentry.m4_migration import parse_assessment_migration

CORPUS = Path(__file__).parents[1] / "corpus-m4"
CASES = sorted(CORPUS.glob("*/expected.json"))


@pytest.mark.parametrize("oracle", CASES, ids=lambda path: path.parent.name)
def test_reviewed_m4_corpus(oracle: Path) -> None:
    folder = oracle.parent
    report = assess(
        load_snapshot(folder / "before.json"),
        load_snapshot(folder / "after.json"),
        migration=parse_assessment_migration((folder / "migration.sql").read_text("utf-8")),
    )
    actual = {
        "analysisStatus": report.analysis_status,
        "overallRisk": report.overall_risk,
        "exitHigh": report_exit(report),
        "findings": [
            {
                "ruleId": finding.rule_id,
                "kind": finding.kind,
                "baseSeverity": finding.base_severity,
                "finalRisk": finding.final_risk,
                "confidence": finding.confidence,
            }
            for finding in report.findings
        ],
    }
    assert actual == json.loads(oracle.read_text("utf-8"))
    assert all(finding.estimated_seconds is None for finding in report.findings)


def test_m4_corpus_floor_and_new_rule_coverage() -> None:
    assert len(CASES) >= 9
    legacy = Path(__file__).parents[1] / "corpus"
    assert len(list(legacy.glob("*/expected.json"))) == 59
    assert len(CASES) + len(list(legacy.glob("*/expected.json"))) >= 68
    for rule in ("SS008", "SS009", "SS010"):
        assert any(
            finding["ruleId"] == rule
            for oracle in CASES
            for finding in json.loads(oracle.read_text("utf-8"))["findings"]
        )
