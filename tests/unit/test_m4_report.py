"""Report schema, deterministic bytes, hostile markup and bounded/atomic failures."""

import json
import os
from pathlib import Path

import jsonschema
import pytest

from schemasentry.assessment import AssessmentNotice, assess
from schemasentry.diff import compare, comparison_json, load_snapshot
from schemasentry.errors import ToolError
from schemasentry.evidence import Evidence, SourceLocation
from schemasentry.m4_migration import parse_assessment_migration
from schemasentry.report import _bounded, escape_markdown, report_json, report_markdown
from schemasentry.report_io import check_output, publish_report, write_checked
from schemasentry.snapshot import Snapshot, to_json

ROOT = Path(__file__).parents[2]
CASE = ROOT / "tests/corpus-m4/0060-check-immediate-validation"


def sample():
    return assess(
        load_snapshot(CASE / "before.json"),
        load_snapshot(CASE / "after.json"),
        migration=parse_assessment_migration((CASE / "migration.sql").read_text("utf-8")),
    )


def golden_sample(hostile=False):
    report = sample()
    if not hostile:
        return report
    text = "<b>x</b> [link](https://evil.invalid) | ```\n# forged\u202e ' &"
    finding = report.findings[0].model_copy(
        update={
            "schema_name": text,
            "object": text,
            "confidence": "low",
            "effects": None,
            "safe_alternative": None,
            "evidence": (Evidence(source="migration", detail=text),),
            "limitations": (text,),
        }
    )
    return report.model_copy(
        update={
            "analysis_status": "incomplete",
            "findings": (finding,),
            "before": report.before.model_copy(update={"captured_at": text}),
            "notices": (
                AssessmentNotice(
                    kind="unsupported_evidence",
                    detail=text,
                    impact="incomplete",
                    location=SourceLocation(start=0, end=10, line=1, column=1),
                ),
            ),
        }
    )


@pytest.mark.parametrize("hostile", [False, True])
def test_markdown_matches_reviewed_complete_and_hostile_goldens(hostile):
    name = "m4-hostile.md" if hostile else "m4-complete.md"
    assert (
        report_markdown(golden_sample(hostile)).encode("utf-8")
        == (ROOT / "tests/golden" / name).read_bytes()
    )


def test_public_report_matches_schema_and_only_estimated_seconds_null():
    report = sample()
    schema = json.loads((ROOT / "docs/schema/report-v1.schema.json").read_text("utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(json.loads(report_json(report)), schema)
    assert json.loads(report_json(report))["findings"][0]["estimatedSeconds"] is None
    assert report_json(report).endswith("\n") and "\r" not in report_json(report)


def test_report_schema_requires_policy_provenance_and_nullable_uncertainty_fields():
    schema = json.loads((ROOT / "docs/schema/report-v1.schema.json").read_text("utf-8"))
    for selected, field in (
        ("report", "policyVersion"),
        ("report", "toolVersion"),
        ("before", "catalogEvidenceVersion"),
        ("finding", "estimatedSeconds"),
        ("finding", "safeAlternative"),
        ("finding", "effects"),
    ):
        document = json.loads(report_json(sample()))
        value = (
            document
            if selected == "report"
            else (document["before"] if selected == "before" else document["findings"][0])
        )
        value.pop(field)
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(document, schema)


def test_repeated_and_shuffled_inputs_preserve_report_bytes_and_diff():
    before, after = load_snapshot(CASE / "before.json"), load_snapshot(CASE / "after.json")
    old_before, old_after, structural = (
        to_json(before),
        to_json(after),
        comparison_json(compare(before, after)),
    )
    migration = parse_assessment_migration((CASE / "migration.sql").read_text("utf-8"))
    original = assess(before, after, migration=migration)
    shuffled = before.model_copy(
        update={
            "tables": [
                table.model_copy(update={"columns": list(reversed(table.columns))})
                for table in reversed(before.tables)
            ]
        }
    )
    repeated = assess(shuffled, after, migration=migration)
    assert report_json(original) == report_json(repeated)
    assert report_markdown(original) == report_markdown(repeated)
    assert to_json(before) == old_before and to_json(after) == old_after
    assert comparison_json(compare(before, after)) == structural


def test_shuffled_catalog_reference_facts_preserve_report_bytes():
    documents = []
    enum_case = ROOT / "tests/corpus-m4/0066-enum-label-removal-rebuild"
    for side in ("before", "after"):
        document = load_snapshot(enum_case / f"{side}.json").model_dump(by_alias=True)
        table = load_snapshot(CASE / "before.json").tables[0].model_dump(by_alias=True)
        for column in table["columns"]:
            column.update(type="state", normalisedType="state")
        document["tables"] = [table]
        catalog = document["catalogEvidence"]
        catalog["relations"] = [{"schema": "public", "table": "users", "kind": "ordinary"}]
        catalog["enumColumns"] = [
            {
                "schema": "public",
                "table": "users",
                "column": name,
                "typeSchema": "public",
                "typeName": "state",
                "mode": "direct",
            }
            for name in ("id", "amount")
        ]
        documents.append(Snapshot.model_validate(document))
    before, after = documents
    original = assess(before, after)
    shuffled = before.model_copy(
        update={
            "catalog_evidence": before.catalog_evidence.model_copy(
                update={"enum_columns": tuple(reversed(before.catalog_evidence.enum_columns))}
            )
        }
    )
    repeated = assess(shuffled, after)
    assert report_json(original) == report_json(repeated)
    assert report_markdown(original) == report_markdown(repeated)


def test_hostile_markdown_controls_and_html_do_not_form_active_markup():
    hostile = "<script>x</script> [click](https://evil.invalid) | ```\n# forged\u202e"
    escaped = escape_markdown(hostile)
    assert "<script>" not in escaped and "```" not in escaped and "\u202e" not in escaped
    assert "&lt;script&gt;" in escaped and "\\[click\\]" in escaped
    assert "\\|" in escaped and "\\\\u000a" in escaped and "\\\\u202e" in escaped
    report = sample()
    changed = report.findings[0].model_copy(
        update={
            "object": hostile,
            "evidence": (Evidence(source="migration", detail=hostile),),
            "safe_alternative": hostile,
        }
    )
    rendered = report_markdown(report.model_copy(update={"findings": (changed,)}))
    assert "\n# forged" not in rendered and "<script>" not in rendered
    assert rendered.endswith("\n") and not rendered.endswith("\n\n")
    assert escape_markdown("' &") == "&#x27; &amp;"


def test_all_bidi_and_invisible_format_controls_are_visible_in_markdown():
    controls = (
        "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e"
        "\u2066\u2067\u2068\u2069\u200b\u200c\u200d\ufeff\u2028\u2029"
    )
    escaped = escape_markdown(controls)
    assert not any(character in escaped for character in controls)
    assert all(f"\\\\u{ord(character):04x}" in escaped for character in controls)


def test_report_size_boundary_and_encoding_reject_without_truncation(monkeypatch):
    monkeypatch.setattr("schemasentry.report.MAX_REPORT_BYTES", 8)
    assert _bounded(["1234567", "\n"]) == "1234567\n"
    with pytest.raises(ToolError, match="16 MiB"):
        _bounded(["12345678", "\n"])
    with pytest.raises(ToolError):
        _bounded(["\ud800"])
    with pytest.raises(ToolError):
        report_json(sample())


class ShortWriter:
    def write(self, text):
        return len(text) - 1

    def flush(self):
        pass


def test_short_writer_is_an_error():
    with pytest.raises(ToolError, match="short"):
        write_checked(ShortWriter(), "complete document")


def test_atomic_failure_preserves_destination_and_removes_owned_stage(tmp_path, monkeypatch):
    destination = tmp_path / "report.json"
    destination.write_text("previous", encoding="utf-8")

    def fail(*args):
        raise OSError("injected rename failure")

    monkeypatch.setattr("schemasentry.report_io.os.replace", fail)
    with pytest.raises(OSError):
        publish_report(destination, "new\n", [])
    assert destination.read_text("utf-8") == "previous"
    assert list(tmp_path.iterdir()) == [destination]


def test_hardlink_output_alias_cannot_overwrite_selected_input(tmp_path):
    selected = tmp_path / "snapshot.json"
    selected.write_bytes(b"selected input")
    destination = tmp_path / "report.json"
    os.link(selected, destination)
    with pytest.raises(ToolError, match="selected input"):
        publish_report(destination, "new", [selected])
    assert selected.read_bytes() == destination.read_bytes() == b"selected input"


def test_symlink_report_destination_is_rejected(tmp_path):
    selected = tmp_path / "snapshot.json"
    selected.write_bytes(b"selected input")
    destination = tmp_path / "report.json"
    try:
        destination.symlink_to(selected)
    except OSError:
        pytest.skip("platform does not permit unprivileged file symlinks")
    with pytest.raises(ToolError, match="regular file"):
        check_output(destination, [selected])
    assert selected.read_bytes() == b"selected input"


def test_fsync_failure_preserves_previous_report(tmp_path, monkeypatch):
    destination = tmp_path / "report.json"
    destination.write_bytes(b"previous")

    def fail(*args):
        raise OSError("injected fsync failure")

    monkeypatch.setattr("schemasentry.report_io.os.fsync", fail)
    with pytest.raises(OSError):
        publish_report(destination, "new\n", [])
    assert destination.read_bytes() == b"previous"
    assert list(tmp_path.iterdir()) == [destination]


def test_flush_failure_is_a_complete_output_error():
    class FlushFailure:
        def write(self, text):
            return len(text)

        def flush(self):
            raise OSError("injected flush failure")

    with pytest.raises(ToolError, match="complete report"):
        write_checked(FlushFailure(), "report\n")
