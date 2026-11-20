"""Boundary rejections cover both assessment inputs and complete report buffers."""

from pathlib import Path

import pytest

from schemasentry.assessment import _object_limits, assess
from schemasentry.catalog_capture import _CatalogBudget, _rows
from schemasentry.diff import compare, load_snapshot
from schemasentry.errors import ToolError
from schemasentry.m4_migration import parse_assessment_migration
from schemasentry.report import MAX_REPORT_BYTES, _bounded, report_json, report_markdown

CASE = Path(__file__).parents[1] / "corpus-m4/0060-check-immediate-validation"


def snapshots():
    return load_snapshot(CASE / "before.json"), load_snapshot(CASE / "after.json")


def test_dynamic_input_string_at_and_over_utf8_bound():
    before, _ = snapshots()
    at = before.model_copy(update={"database": "é" * (256 * 1024 // 2)})
    assert assess(at, at).analysis_status == "complete"
    over = at.model_copy(update={"database": at.database + "x"})
    with pytest.raises(ToolError, match="dynamic string"):
        assess(over, over)
    invalid = before.model_copy(update={"database": "\ud800"})
    with pytest.raises(ToolError, match="UTF-8"):
        assess(invalid, before)


def test_duplicate_column_positions_cannot_make_report_digests_ambiguous():
    before, _ = snapshots()
    table = before.tables[0]
    ambiguous = before.model_copy(
        update={
            "tables": [
                table.model_copy(
                    update={"columns": [c.model_copy(update={"ordinal": 1}) for c in table.columns]}
                )
            ]
        }
    )
    assert not compare(before, ambiguous).changes
    with pytest.raises(ToolError, match="duplicate column positions"):
        assess(before, ambiguous)


def test_combined_object_bound_is_checked_before_classification(monkeypatch):
    before, after = snapshots()
    boundary = _object_limits(before) + _object_limits(after)
    monkeypatch.setattr("schemasentry.assessment.MAX_OBJECTS", boundary)
    assert assess(before, after).findings
    monkeypatch.setattr("schemasentry.assessment.MAX_OBJECTS", boundary - 1)
    with pytest.raises(ToolError, match="combined object bound"):
        assess(before, after)


def test_finding_and_notice_bounds_fail_without_truncating(monkeypatch):
    before, after = snapshots()
    migration = parse_assessment_migration((CASE / "migration.sql").read_text("utf-8"))
    monkeypatch.setattr("schemasentry.assessment.MAX_FINDINGS", 1)
    assert len(assess(before, after, migration=migration).findings) == 1
    monkeypatch.setattr("schemasentry.assessment.MAX_FINDINGS", 0)
    with pytest.raises(ToolError, match="finding or notice bound"):
        assess(before, after, migration=migration)
    monkeypatch.setattr("schemasentry.assessment.MAX_FINDINGS", 1)
    unknown = before.model_copy(update={"catalog_evidence": None})
    expected = assess(unknown, unknown)
    monkeypatch.setattr("schemasentry.assessment.MAX_NOTICES", len(expected.notices))
    assert assess(unknown, unknown).notices == expected.notices
    monkeypatch.setattr("schemasentry.assessment.MAX_NOTICES", len(expected.notices) - 1)
    with pytest.raises(ToolError, match="finding or notice bound"):
        assess(unknown, unknown)


def test_actual_report_byte_bound_counts_encoded_utf8_and_keeps_last_byte():
    text = "é" * (MAX_REPORT_BYTES // 2 - 1) + "x\n"
    assert len(text.encode("utf-8")) == MAX_REPORT_BYTES
    assert _bounded([text]) == text
    with pytest.raises(ToolError, match="16 MiB"):
        _bounded([text, "x"])


@pytest.mark.parametrize("renderer", [report_json, report_markdown])
def test_both_renderers_enforce_the_entire_document_boundary(renderer, monkeypatch):
    before, after = snapshots()
    report = assess(before, after)
    expected = renderer(report)
    monkeypatch.setattr("schemasentry.report.MAX_REPORT_BYTES", len(expected.encode("utf-8")))
    assert renderer(report) == expected
    monkeypatch.setattr("schemasentry.report.MAX_REPORT_BYTES", len(expected.encode("utf-8")) - 1)
    with pytest.raises(ToolError, match="16 MiB"):
        renderer(report)


def test_catalog_queries_share_remaining_budget_and_request_one_over_limit():
    limits = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, query, parameters):
            limits.append(parameters[1])

        def fetchall(self):
            return [{}, {}]

    class Connection:
        def cursor(self, **kwargs):
            return Cursor()

    budget = _CatalogBudget(remaining=3)
    query = "SELECT 1 WHERE 'public'=ANY(%s) LIMIT %s"
    assert len(_rows(Connection(), query, ["public"], budget)) == 2
    with pytest.raises(ToolError, match="row bound"):
        _rows(Connection(), query, ["public"], budget)
    assert limits == [4, 2]
