"""Distinct known risk modifiers, caps and uncertainty without fabricated seconds."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from schemasentry.assessment import LEVELS, assess, report_exit, score_finding
from schemasentry.catalog_models import IncomingForeignKey
from schemasentry.diff import load_snapshot
from schemasentry.evidence import Evidence, Finding

CASE = Path(__file__).parents[1] / "corpus-m4" / "0063-index-ordinary-build"


def baseline():
    return load_snapshot(CASE / "before.json")


def finding(severity="low", confidence="high"):
    return Finding(
        rule_id="SS009",
        schema="public",
        table="users",
        object="idx",
        kind="test",
        base_severity=severity,
        confidence=confidence,
        evidence=(Evidence(source="snapshot", detail="Reviewed input."),),
        limitations=(),
    )


@pytest.mark.parametrize(
    "rows,bump", [(999_999, 0), (1_000_000, 0), (1_000_001, 1), (20_000_000, 1), (20_000_001, 2)]
)
def test_exact_size_tiers(rows, bump):
    before = baseline()
    before = before.model_copy(
        update={"tables": [before.tables[0].model_copy(update={"row_estimate": rows})]}
    )
    scored = score_finding(finding(), before)
    assert scored.modifiers[0].contribution == bump
    assert scored.final_risk == LEVELS[bump]
    assert scored.estimated_seconds is None


@pytest.mark.parametrize("count,bump", [(0, 0), (1, 0), (2, 1), (3, 1)])
def test_distinct_incoming_fk_boundary(count, bump):
    before = baseline()
    assert before.catalog_evidence is not None
    refs = tuple(
        IncomingForeignKey(
            schema="outside",
            table="source",
            name=f"fk_{index}",
            target_schema="public",
            target_table="users",
            target_columns=("id",),
        )
        for index in range(count)
    )
    before = before.model_copy(
        update={
            "catalog_evidence": before.catalog_evidence.model_copy(
                update={"incoming_foreign_keys": refs}
            )
        }
    )
    scored = score_finding(finding(), before)
    assert scored.modifiers[1].value == count
    assert scored.modifiers[1].contribution == bump
    assert scored.final_risk == LEVELS[bump]


def test_known_modifiers_add_once_and_cap_with_confidence_retained():
    before = baseline()
    assert before.catalog_evidence is not None
    refs = tuple(
        IncomingForeignKey(
            schema="outside",
            table="source",
            name=f"fk_{index}",
            target_schema="public",
            target_table="users",
            target_columns=("id",),
        )
        for index in range(2)
    )
    before = before.model_copy(
        update={
            "tables": [before.tables[0].model_copy(update={"row_estimate": 20_000_001})],
            "catalog_evidence": before.catalog_evidence.model_copy(
                update={"incoming_foreign_keys": refs}
            ),
        }
    )
    original = finding("high", "low")
    scored = score_finding(original, before)
    assert scored.final_risk == "critical"
    assert [modifier.contribution for modifier in scored.modifiers] == [2, 1, 0]
    assert original.base_severity == "high" and scored.confidence == "low"
    assert "finalRisk" not in original.model_dump(by_alias=True)
    with pytest.raises(ValidationError):
        scored.final_risk = "low"


def test_unknown_modifiers_are_explicit_and_do_not_lower_base():
    before = baseline()
    before = before.model_copy(
        update={
            "tables": [before.tables[0].model_copy(update={"row_estimate": None})],
            "catalog_evidence": None,
        }
    )
    scored = score_finding(finding("high"), before)
    assert scored.final_risk == "high"
    assert [modifier.status for modifier in scored.modifiers] == ["unknown"] * 3
    assert all(modifier.contribution == 0 for modifier in scored.modifiers)
    assert scored.estimated_seconds is None


def test_incomplete_precedes_critical_and_threshold_never_suppresses_critical():
    before = baseline()
    after = before.model_copy(update={"tables": []})
    assert after.catalog_evidence is not None
    after = after.model_copy(
        update={"catalog_evidence": after.catalog_evidence.model_copy(update={"relations": ()})}
    )
    for threshold in LEVELS:
        report = assess(before, after, threshold=threshold)
        assert report.overall_risk == "critical" and report_exit(report) == 2
        assert report_exit(report.model_copy(update={"analysis_status": "incomplete"})) == 3
