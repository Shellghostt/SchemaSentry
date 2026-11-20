"""Strict catalog versions, complete scoped facts, and explicit legacy unknowns."""

import json
from pathlib import Path

import jsonschema
import pytest

from schemasentry.assessment import assess, report_exit
from schemasentry.diff import compare, load_snapshot
from schemasentry.errors import ToolError
from schemasentry.snapshot import Snapshot, to_json

ROOT = Path(__file__).parents[2]
CORPUS = ROOT / "tests/corpus-m4"


def payload(case=60, side="after"):
    path = next(CORPUS.glob(f"{case:04d}-*")) / f"{side}.json"
    return json.loads(path.read_text("utf-8"))


@pytest.mark.parametrize(
    "field", ["scopeSchemas", "relations", "constraintValidity", "enums", "enumColumns"]
)
def test_duplicate_catalog_facts_are_rejected(field, tmp_path):
    document = payload(67) if field in ("enums", "enumColumns") else payload()
    if field == "enumColumns":
        document = payload()
        document["tables"][0]["columns"][1].update(type="state", normalisedType="state")
        document["catalogEvidence"]["enums"] = [
            {"schema": "public", "name": "state", "labels": ["ready"]}
        ]
        document["catalogEvidence"]["enumColumns"] = [
            {
                "schema": "public",
                "table": "users",
                "column": "amount",
                "typeSchema": "public",
                "typeName": "state",
                "mode": "direct",
            }
        ]
    values = document["catalogEvidence"][field]
    values.append(values[0])
    path = tmp_path / "duplicate.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ToolError):
        load_snapshot(path)


@pytest.mark.parametrize("version", [True, 1.0, 2, "1", None])
def test_catalog_version_is_strict_and_explicit(version, tmp_path):
    document = payload()
    if version is None:
        document["catalogEvidence"].pop("evidenceVersion")
    else:
        document["catalogEvidence"]["evidenceVersion"] = version
    path = tmp_path / "version.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ToolError):
        load_snapshot(path)


@pytest.mark.parametrize("field", ["scopeSchemas", "relations", "constraintValidity"])
def test_inconsistent_scope_relations_and_constraint_validity_are_rejected(field, tmp_path):
    document = payload()
    document["catalogEvidence"][field] = []
    path = tmp_path / "inconsistent.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ToolError):
        load_snapshot(path)


def test_enum_reference_cannot_point_at_an_integer_column(tmp_path):
    document = payload()
    document["catalogEvidence"]["enums"] = [
        {"schema": "public", "name": "state", "labels": ["ready"]}
    ]
    document["catalogEvidence"]["enumColumns"] = [
        {
            "schema": "public",
            "table": "users",
            "column": "amount",
            "typeSchema": "public",
            "typeName": "state",
            "mode": "direct",
        }
    ]
    path = tmp_path / "type.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ToolError, match="column type"):
        load_snapshot(path)


def test_incoming_fk_matches_scoped_source_and_cannot_omit_it(tmp_path):
    document = payload(60, "before")
    table = document["tables"][0]
    table["constraints"] = [
        {
            "name": "self_fk",
            "kind": "foreign_key",
            "columns": ["amount"],
            "referencedTable": "public.users",
            "referencedColumns": ["id"],
            "definition": "FOREIGN KEY (amount) REFERENCES users(id)",
        }
    ]
    catalog = document["catalogEvidence"]
    catalog["constraintValidity"] = [
        {
            "schema": "public",
            "table": "users",
            "name": "self_fk",
            "kind": "foreign_key",
            "validated": True,
        }
    ]
    path = tmp_path / "foreign.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ToolError, match="omits"):
        load_snapshot(path)
    foreign = {
        "schema": "public",
        "table": "users",
        "name": "self_fk",
        "targetSchema": "public",
        "targetTable": "users",
        "targetColumns": ["id"],
    }
    catalog["incomingForeignKeys"] = [foreign]
    path.write_text(json.dumps(document), encoding="utf-8")
    valid = load_snapshot(path)
    assert valid.catalog_evidence.incoming_foreign_keys[0].target_columns == ("id",)
    foreign["targetColumns"] = ["amount"]
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ToolError, match="source constraint"):
        load_snapshot(path)


def test_python_model_copy_cannot_bypass_catalog_duplicates():
    valid = Snapshot.model_validate(payload())
    catalog = valid.catalog_evidence
    invalid = valid.model_copy(
        update={"catalog_evidence": catalog.model_copy(update={"relations": catalog.relations * 2})}
    )
    with pytest.raises(ToolError, match="duplicate"):
        compare(valid, invalid)


def test_known_empty_catalog_differs_from_legacy_omission_and_schema_accepts_both():
    known = Snapshot.model_validate(payload(60, "before"))
    legacy = known.model_copy(update={"catalog_evidence": None})
    assert "catalogEvidence" not in to_json(legacy)
    complete, incomplete = assess(known, known), assess(legacy, legacy)
    assert complete.analysis_status == "complete" and report_exit(complete) == 0
    assert incomplete.analysis_status == "incomplete" and report_exit(incomplete) == 3
    assert complete.before.catalog_evidence_version == 1
    assert incomplete.before.catalog_evidence_version is None
    schema = json.loads((ROOT / "docs/schema/snapshot-v1.schema.json").read_text("utf-8"))
    for snapshot in (known, legacy):
        jsonschema.validate(json.loads(to_json(snapshot)), schema)
