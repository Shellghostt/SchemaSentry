"""PostgreSQL validation stages and conservative binding to observed M4 evidence."""

from pathlib import Path

import pytest

from schemasentry.assessment import assess, report_exit
from schemasentry.classification import classify
from schemasentry.diff import load_snapshot
from schemasentry.m4_migration import parse_assessment_migration
from schemasentry.snapshot import Snapshot

CORPUS = Path(__file__).parents[1] / "corpus-m4"


def snapshot(case, side):
    return load_snapshot(next(CORPUS.glob(f"{case:04d}-*")) / f"{side}.json")


def assessment(before, after, source):
    return assess(before, after, migration=parse_assessment_migration(source))


def test_existing_not_valid_check_validation_has_its_own_scan_and_lock():
    before = snapshot(61, "after")
    after = snapshot(60, "after")
    report = assessment(
        before, after, "ALTER TABLE public.users VALIDATE CONSTRAINT amount_positive;"
    )
    assert report.analysis_status == "complete" and report_exit(report) == 1
    assert len(report.findings) == 1
    finding = report.findings[0]
    assert finding.rule_id == "SS008" and finding.confidence == "high"
    assert finding.kind == "constraint_validation_requested"
    assert finding.effects.lock_level == "share_update_exclusive"
    assert finding.effects.scan == "required" and finding.effects.rewrite == "not_required"


def test_added_not_valid_then_validation_preserves_both_requested_stages():
    report = assessment(
        snapshot(60, "before"),
        snapshot(60, "after"),
        "ALTER TABLE public.users ADD CONSTRAINT amount_positive CHECK (amount > 0) NOT VALID; "
        "ALTER TABLE public.users VALIDATE CONSTRAINT amount_positive;",
    )
    assert report.analysis_status == "complete" and report_exit(report) == 1
    finding = report.findings[0]
    assert finding.effects.lock_level == "access_exclusive" and finding.effects.scan == "required"
    assert len([e for e in finding.evidence if e.source == "migration"]) == 2


def test_validation_transition_without_sql_retains_uncertainty():
    report = assess(snapshot(61, "after"), snapshot(60, "after"))
    assert report.analysis_status == "incomplete" and report_exit(report) == 3
    assert report.findings[0].rule_id == "SS008" and report.findings[0].confidence == "low"


def test_revalidating_an_already_valid_check_does_not_claim_a_new_scan():
    before = snapshot(60, "after")
    report = assessment(
        before, before, "ALTER TABLE public.users VALIDATE CONSTRAINT amount_positive;"
    )
    assert report.analysis_status == "complete" and not report.findings


@pytest.mark.parametrize(
    "source",
    [
        "ALTER TABLE public.users ADD CONSTRAINT amount_positive CHECK (amount > 0);",
        "ALTER TABLE public.users VALIDATE CONSTRAINT missing_constraint;",
    ],
)
def test_constraint_sql_without_observed_object_is_incomplete(source):
    before = snapshot(60, "before")
    report = assessment(before, before, source)
    assert report.analysis_status == "incomplete" and report_exit(report) == 3


@pytest.mark.parametrize(
    "source",
    [
        "ALTER TYPE public.state ADD VALUE 'unobserved';",
        "ALTER TYPE public.state RENAME VALUE 'ready' TO 'unobserved';",
        "DROP TYPE public.state;",
        "CREATE TYPE public.state AS ENUM ('unobserved');",
    ],
)
def test_enum_sql_cannot_establish_unobserved_membership_changes(source):
    before = snapshot(67, "before")
    report = assessment(before, before, source)
    assert report.analysis_status == "incomplete" and report_exit(report) == 3


@pytest.mark.parametrize("version", ["17.1", "16.5"])
@pytest.mark.parametrize("case", [60, 63, 66])
def test_unconfirmed_versions_never_establish_new_rule_effects(version, case):
    before, after = snapshot(case, "before"), snapshot(case, "after")
    after = after.model_copy(update={"server_version": version})
    source = (next(CORPUS.glob(f"{case:04d}-*")) / "migration.sql").read_text("utf-8")
    report = assessment(before, after, source)
    assert report.analysis_status == "incomplete" and report_exit(report) == 3
    assert report.findings[0].confidence == "low" and report.findings[0].effects is None


@pytest.mark.parametrize("case", [60, 63, 66])
@pytest.mark.parametrize("side", ["before", "after"])
def test_each_new_rule_retains_missing_catalog_evidence(case, side):
    before, after = snapshot(case, "before"), snapshot(case, "after")
    if side == "before":
        before = before.model_copy(update={"catalog_evidence": None})
    else:
        after = after.model_copy(update={"catalog_evidence": None})
    source = (next(CORPUS.glob(f"{case:04d}-*")) / "migration.sql").read_text("utf-8")
    report = assessment(before, after, source)
    assert report.analysis_status == "incomplete" and report_exit(report) == 3
    assert any(notice.kind == "catalog_evidence_missing" for notice in report.notices)


def test_direct_enum_drop_value_syntax_remains_unsupported():
    report = assessment(
        snapshot(66, "before"), snapshot(66, "after"), "ALTER TYPE public.state DROP VALUE 'ready';"
    )
    assert report.overall_risk == "critical" and report_exit(report) == 3
    assert any(notice.kind == "unanalysable_statement" for notice in report.notices)


@pytest.mark.parametrize(
    "source",
    [
        "BEGIN; CREATE INDEX users_amount ON public.users(amount);",
        "BEGIN; CREATE INDEX users_amount ON public.users(amount); ROLLBACK;",
        "BEGIN; BEGIN; CREATE INDEX users_amount ON public.users(amount); COMMIT; COMMIT;",
        "SAVEPOINT stage; CREATE INDEX users_amount ON public.users(amount);",
        "CREATE INDEX users_amount ON public.users(lower(amount::text));",
        "CREATE INDEX IF NOT EXISTS users_amount ON public.users(amount);",
    ],
)
def test_unsupported_index_syntax_or_transaction_remains_visible(source):
    report = assessment(snapshot(63, "before"), snapshot(63, "after"), source)
    assert report.analysis_status == "incomplete" and report_exit(report) == 3
    assert any(notice.impact == "incomplete" for notice in report.notices)


def test_rollback_of_legacy_operation_is_incomplete_in_public_assessment():
    before = snapshot(60, "before")
    payload = before.model_dump(by_alias=True)
    payload["tables"][0]["columns"] = [payload["tables"][0]["columns"][0]]
    after = Snapshot.model_validate(payload)
    report = assessment(
        before, after, "BEGIN; ALTER TABLE public.users DROP COLUMN amount; ROLLBACK;"
    )
    assert report.analysis_status == "incomplete" and report_exit(report) == 3


def test_quoted_schema_table_column_and_constraint_bind_without_case_folding():
    documents = []
    for side in ("before", "after"):
        payload = snapshot(60, side).model_dump(by_alias=True)
        payload["schemas"] = ["Odd.Schema"]
        table = payload["tables"][0]
        table["schema"], table["name"] = "Odd.Schema", "Users"
        table["columns"][1]["name"] = "Amount"
        for constraint in table["constraints"]:
            constraint.update(
                name="Positive-Amount", columns=["Amount"], definition='CHECK ("Amount" > 0)'
            )
        catalog = payload["catalogEvidence"]
        catalog["scopeSchemas"] = ["Odd.Schema"]
        for relation in catalog["relations"]:
            relation.update(schema="Odd.Schema", table="Users")
        for fact in catalog["constraintValidity"]:
            fact.update(schema="Odd.Schema", table="Users", name="Positive-Amount")
        documents.append(Snapshot.model_validate(payload))
    report = assessment(
        *documents,
        'ALTER TABLE "Odd.Schema"."Users" ADD CONSTRAINT "Positive-Amount" CHECK ("Amount" > 0);',
    )
    assert report.analysis_status == "complete" and report_exit(report) == 1
    assert report.findings[0].schema_name == "Odd.Schema"
    assert report.findings[0].object == "Positive-Amount"


@pytest.mark.parametrize("extra", ["", " SELECT now();"])
def test_supported_m4_statements_do_not_poison_legacy_lock_evidence(extra):
    before = snapshot(60, "before")
    payload = snapshot(60, "after").model_dump(by_alias=True)
    payload["tables"][0]["columns"] = [payload["tables"][0]["columns"][1]]
    after = Snapshot.model_validate(payload)
    source = (
        "ALTER TABLE public.users ADD CONSTRAINT amount_positive CHECK (amount > 0); "
        "ALTER TABLE public.users DROP COLUMN id;" + extra
    )
    migration = parse_assessment_migration(source)
    original_bytes = migration.legacy.model_dump_json()
    original = classify(before, after, migration=migration.legacy, default_schema="public")
    report = assess(before, after, migration=migration)
    effects = next(f for f in report.findings if f.rule_id == "SS005")
    assert len(report.findings) == 3
    if extra:
        assert report.analysis_status == "incomplete" and report_exit(report) == 3
        assert effects.confidence == "low" and effects.effects.scan == "unknown"
        assert any(n.kind == "unanalysable_statement" for n in report.notices)
    else:
        assert report.analysis_status == "complete" and report_exit(report) == 2
        assert effects.confidence == "high" and effects.effects.lock_level == "access_exclusive"
        assert effects.effects.scan == effects.effects.rewrite == "not_required"
    assert migration.legacy.model_dump_json() == original_bytes
    assert classify(before, after, migration=migration.legacy, default_schema="public") == original


def test_partitioned_constraint_effects_remain_unconfirmed():
    documents = []
    for side in ("before", "after"):
        payload = snapshot(60, side).model_dump(by_alias=True)
        payload["catalogEvidence"]["relations"][0]["kind"] = "partitioned"
        documents.append(Snapshot.model_validate(payload))
    report = assessment(
        *documents,
        "ALTER TABLE public.users ADD CONSTRAINT amount_positive CHECK (amount > 0);",
    )
    assert report_exit(report) == 3
    assert report.findings[0].confidence == "low" and report.findings[0].effects is None
