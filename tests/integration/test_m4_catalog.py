"""Owned live databases: M4 facts, read-only capture, rule accuracy and cross-schema FK scope."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from schemasentry.assessment import assess, report_exit, score_finding
from schemasentry.config import DATABASE_URL_ENV
from schemasentry.evidence import Finding
from schemasentry.introspect import capture_snapshot
from schemasentry.m4_migration import parse_assessment_migration
from schemasentry.snapshot import to_json

DSN = os.environ.get("SCHEMASENTRY_TEST_DATABASE_URL")
CAPTURED_AT = "2026-11-20T00:00:00Z"
pytestmark = pytest.mark.skipif(not DSN, reason="set disposable SCHEMASENTRY_TEST_DATABASE_URL")


@pytest.fixture
def database() -> Iterator[tuple[str, psycopg.Connection[Any]]]:
    assert DSN is not None
    name = "ss_m4_" + uuid.uuid4().hex
    with psycopg.connect(DSN, autocommit=True, connect_timeout=10) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    dsn = make_conninfo(DSN, dbname=name)
    try:
        with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as connection:
            connection.execute("SET statement_timeout='10s'")
            yield dsn, connection
    finally:
        with psycopg.connect(DSN, autocommit=True, connect_timeout=10) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def capture(dsn):
    return capture_snapshot(
        dsn, schemas=["public"], captured_at=CAPTURED_AT, analysis_evidence=True
    )


def seed(connection):
    connection.execute(
        "CREATE TABLE public.users (id integer PRIMARY KEY, amount integer NOT NULL)"
    )
    connection.execute("INSERT INTO public.users VALUES (1,1)")
    connection.execute("ANALYZE public.users")


@pytest.mark.parametrize("not_valid", [False, True])
def test_live_check_validation_and_locks(database, not_valid):
    dsn, connection = database
    seed(connection)
    before = capture(dsn)
    source = "ALTER TABLE public.users ADD CONSTRAINT positive_amount CHECK (amount > 0)" + (
        " NOT VALID" if not_valid else ""
    )
    with connection.transaction():
        connection.execute(source)
        modes = connection.execute(
            "SELECT mode FROM pg_locks WHERE pid=pg_backend_pid() AND relation"
            "='public.users'::regclass AND granted"
        ).fetchall()
        assert ("AccessExclusiveLock",) in modes
    after = capture(dsn)
    assert after.catalog_evidence is not None
    facts = after.catalog_evidence.constraint_validity
    assert len(facts) == 1 and facts[0].validated is not not_valid
    report = assess(before, after, migration=parse_assessment_migration(source))
    findings = [finding for finding in report.findings if finding.rule_id == "SS008"]
    assert report.analysis_status == "complete"
    assert bool(findings) is not not_valid
    if findings:
        assert findings[0].effects is not None
        assert findings[0].effects.lock_level == "access_exclusive"
        assert findings[0].effects.scan == "required"


def test_live_fk_validation_and_outside_schema_exposure(database):
    dsn, connection = database
    seed(connection)
    connection.execute("CREATE TABLE public.orders (id integer, user_id integer)")
    before = capture(dsn)
    source = (
        "ALTER TABLE public.orders ADD CONSTRAINT user_fk FOREIGN KEY (use"
        "r_id) REFERENCES public.users (id)"
    )
    with connection.transaction():
        connection.execute(source)
        modes = connection.execute(
            "SELECT mode FROM pg_locks WHERE pid=pg_backend_pid() AND relation"
            "='public.orders'::regclass AND granted"
        ).fetchall()
        assert ("ShareRowExclusiveLock",) in modes
    report = assess(before, capture(dsn), migration=parse_assessment_migration(source))
    assert report.analysis_status == "complete"
    assert any(finding.rule_id == "SS008" for finding in report.findings)
    connection.execute("CREATE SCHEMA outside")
    connection.execute(
        "CREATE TABLE outside.references_users (a integer REFERENCES publi"
        "c.users(id), b integer REFERENCES public.users(id))"
    )
    snapshot = capture(dsn)
    assert snapshot.catalog_evidence is not None
    incoming = [
        fact
        for fact in snapshot.catalog_evidence.incoming_foreign_keys
        if fact.target_table == "users"
    ]
    assert len(incoming) == 3 and sum(fact.schema_name == "outside" for fact in incoming) == 2
    finding = Finding(
        rule_id="SS009",
        schema="public",
        table="users",
        object="idx",
        kind="test",
        base_severity="low",
        confidence="high",
        evidence=(),
        limitations=(),
    )
    scored = score_finding(finding, snapshot)
    assert scored.modifiers[1].contribution == 1 and scored.modifiers[1].value == 3


@pytest.mark.parametrize("kind", ["check", "foreign_key"])
def test_live_existing_constraint_validation_scan_and_lock(database, kind):
    dsn, connection = database
    seed(connection)
    if kind == "check":
        table, name = "users", "amount_positive"
        addition = "ALTER TABLE public.users ADD CONSTRAINT amount_positive CHECK (amount > 0)"
    else:
        connection.execute("CREATE TABLE public.orders (user_id integer)")
        table, name = "orders", "user_fk"
        addition = (
            "ALTER TABLE public.orders ADD CONSTRAINT user_fk FOREIGN KEY (user_id) "
            "REFERENCES public.users(id)"
        )
    connection.execute(addition + " NOT VALID")
    before = capture(dsn)
    source = f"ALTER TABLE public.{table} VALIDATE CONSTRAINT {name}"
    with connection.transaction():
        connection.execute(source)
        locks = connection.execute(
            "SELECT c.relname,l.mode FROM pg_locks l JOIN pg_class c ON c.oid=l.relation "
            "WHERE l.pid=pg_backend_pid() AND l.granted"
        ).fetchall()
        assert (table, "ShareUpdateExclusiveLock") in locks
        if kind == "foreign_key":
            assert ("users", "RowShareLock") in locks
    after = capture(dsn)
    report = assess(before, after, migration=parse_assessment_migration(source))
    assert report.analysis_status == "complete" and report_exit(report) == 1
    finding = next(f for f in report.findings if f.rule_id == "SS008")
    assert finding.effects.lock_level == "share_update_exclusive"
    assert finding.effects.scan == "required" and finding.estimated_seconds is None
    assert assess(before, after).analysis_status == "incomplete"
    connection.execute(source)
    repeated = assess(after, capture(dsn), migration=parse_assessment_migration(source))
    assert repeated.analysis_status == "complete"
    assert not any(f.rule_id == "SS008" for f in repeated.findings)


@pytest.mark.parametrize("concurrent", [False, True])
def test_live_index_build_mode(database, concurrent):
    dsn, connection = database
    seed(connection)
    before = capture(dsn)
    source = (
        "CREATE INDEX "
        + ("CONCURRENTLY " if concurrent else "")
        + "users_amount ON public.users(amount)"
    )
    if concurrent:
        connection.execute(source)
    else:
        with connection.transaction():
            connection.execute(source)
            modes = connection.execute(
                "SELECT mode FROM pg_locks WHERE pid=pg_backend_pid() AND relation"
                "='public.users'::regclass AND granted"
            ).fetchall()
            assert ("ShareLock",) in modes
    report = assess(before, capture(dsn), migration=parse_assessment_migration(source))
    assert report.analysis_status == "complete"
    assert (
        bool([finding for finding in report.findings if finding.rule_id == "SS009"])
        is not concurrent
    )


def test_live_concurrent_index_transaction_and_partition_restrictions(database):
    dsn, connection = database
    seed(connection)
    before = capture(dsn)
    with pytest.raises(psycopg.Error) as failure, connection.transaction():
        connection.execute("CREATE INDEX CONCURRENTLY users_amount ON public.users(amount)")
    assert failure.value.sqlstate == "25001"
    report = assess(
        before,
        capture(dsn),
        migration=parse_assessment_migration(
            "BEGIN; CREATE INDEX CONCURRENTLY users_amount ON public.users(amount); COMMIT;"
        ),
    )
    assert report_exit(report) == 2
    connection.execute("CREATE TABLE public.parts (id integer) PARTITION BY RANGE(id)")
    before = capture(dsn)
    with pytest.raises(psycopg.Error) as partition_failure:
        connection.execute("CREATE INDEX CONCURRENTLY parts_id ON public.parts(id)")
    assert partition_failure.value.sqlstate == "0A000"
    report = assess(
        before,
        capture(dsn),
        migration=parse_assessment_migration(
            "CREATE INDEX CONCURRENTLY parts_id ON public.parts(id);"
        ),
    )
    assert any(
        finding.kind == "concurrent_partitioned_index_unsupported" for finding in report.findings
    )


def test_live_enum_labels_rename_arrays_and_domain_uncertainty(database):
    dsn, connection = database
    connection.execute("CREATE TYPE public.state AS ENUM ('draft','ready')")
    connection.execute("CREATE TABLE public.items (state public.state, states public.state[])")
    before = capture(dsn)
    assert before.catalog_evidence is not None
    assert before.catalog_evidence.enums[0].labels == ("draft", "ready")
    assert {reference.mode for reference in before.catalog_evidence.enum_columns} == {
        "direct",
        "array",
    }
    source = "ALTER TYPE public.state RENAME VALUE 'ready' TO 'done'"
    connection.execute(source)
    after = capture(dsn)
    report = assess(before, after, migration=parse_assessment_migration(source))
    assert report.analysis_status == "complete"
    assert any(finding.kind == "enum_label_renamed" for finding in report.findings)
    connection.execute("CREATE DOMAIN public.state_domain AS public.state")
    connection.execute("ALTER TABLE public.items ADD COLUMN domain_state public.state_domain")
    domain = capture(dsn)
    report = assess(domain, domain)
    assert report.analysis_status == "incomplete" and report_exit(report) == 3


def test_live_enum_rebuild_removal_and_default_snapshot_compatibility(database):
    dsn, connection = database
    connection.execute("CREATE TYPE public.state AS ENUM ('draft','ready')")
    legacy = capture_snapshot(dsn, schemas=["public"], captured_at=CAPTURED_AT)
    assert "catalogEvidence" not in to_json(legacy)
    before = capture(dsn)
    source = "DROP TYPE public.state; CREATE TYPE public.state AS ENUM ('draft')"
    connection.execute(source)
    after = capture(dsn)
    report = assess(before, after, migration=parse_assessment_migration(source))
    assert report.analysis_status == "complete" and report_exit(report) == 2
    assert report.findings[0].kind == "enum_labels_removed"


def test_live_known_empty_enum_is_not_legacy_unknown(database):
    dsn, connection = database
    connection.execute("CREATE TYPE public.empty_state AS ENUM ()")
    known = capture(dsn)
    assert known.catalog_evidence.enums[0].labels == ()
    assert assess(known, known).analysis_status == "complete"
    legacy = known.model_copy(update={"catalog_evidence": None})
    assert assess(legacy, legacy).analysis_status == "incomplete"


@pytest.mark.parametrize("wrapper", ["domain_array", "composite_array", "outside_enum"])
def test_live_uncaptured_type_dependencies_remain_incomplete(database, wrapper):
    dsn, connection = database
    if wrapper == "domain_array":
        connection.execute("CREATE TYPE public.state AS ENUM ('ready')")
        connection.execute("CREATE DOMAIN public.state_domain AS public.state")
        connection.execute("CREATE TABLE public.items (state public.state_domain[])")
    elif wrapper == "composite_array":
        connection.execute("CREATE TYPE public.composite_state AS (value integer)")
        connection.execute("CREATE TABLE public.items (state public.composite_state[])")
    else:
        connection.execute("CREATE SCHEMA outside")
        connection.execute("CREATE TYPE outside.state AS ENUM ('ready')")
        connection.execute("CREATE TABLE public.items (state outside.state)")
    document = capture(dsn)
    report = assess(document, document)
    assert report.analysis_status == "incomplete" and report_exit(report) == 3
    assert any(n.kind == "enum_dependency_unavailable" for n in report.notices)


def test_m4_capture_keeps_read_only_repeatable_read_and_statement_timeout(database, monkeypatch):
    from schemasentry.catalog_capture import capture_catalog

    dsn, connection = database
    seed(connection)

    # Inspect settings without injecting a failed SQL transaction into the production collector.
    def settings_only(transaction, snapshot):
        assert (
            transaction.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"]
            == "on"
        )
        assert (
            transaction.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"]
            == "repeatable read"
        )
        assert transaction.execute("SHOW statement_timeout").fetchone()["statement_timeout"] == "5s"
        return capture_catalog(transaction, snapshot)

    monkeypatch.setattr("schemasentry.introspect.capture_catalog", settings_only)
    assert capture(dsn).catalog_evidence is not None


def test_live_compare_observes_baseline_scope_and_never_executes_migration(database, tmp_path):
    dsn, connection = database
    seed(connection)
    baseline = tmp_path / "before.json"
    baseline.write_bytes(to_json(capture(dsn)).encode("utf-8"))
    migration = tmp_path / "requested.sql"
    migration.write_text("ALTER TABLE public.users DROP COLUMN amount;", encoding="utf-8")
    environment = dict(os.environ)
    environment[DATABASE_URL_ENV] = make_conninfo(dsn, application_name="DO_NOT_PRINT_CONFIG")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "schemasentry",
            "compare",
            "--baseline",
            str(baseline),
            "--migration",
            str(migration),
            "--format",
            "json",
            "--captured-at",
            CAPTURED_AT,
        ],
        capture_output=True,
        env=environment,
        timeout=20,
        check=False,
    )
    assert result.returncode == 3
    report = json.loads(result.stdout)
    assert report["analysisStatus"] == "incomplete"
    assert report["after"]["catalogEvidenceVersion"] == 1
    assert any(n["kind"] == "statement_snapshot_evidence_unconfirmed" for n in report["notices"])
    assert connection.execute("SELECT amount FROM public.users").fetchall() == [(1,)]
    assert b"DO_NOT_PRINT_CONFIG" not in result.stdout + result.stderr
    assert b"Traceback" not in result.stderr and b"\r" not in result.stdout
