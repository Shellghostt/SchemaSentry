"""Live M3 corpus: apply committed synthetic SQL inside a newly created disposable database."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from schemasentry.classification import classify
from schemasentry.diff import compare, load_snapshot
from schemasentry.errors import ToolError
from schemasentry.hints import load_hints
from schemasentry.introspect import capture_snapshot
from schemasentry.migration import load_migration
from schemasentry.snapshot import Snapshot

DSN = os.environ.get("SCHEMASENTRY_TEST_DATABASE_URL")
CORPUS = Path(__file__).resolve().parents[1] / "corpus"
CASES = sorted(CORPUS.glob("*/expected.json"))
CAPTURED_AT = "2026-11-15T00:00:00Z"

pytestmark = pytest.mark.skipif(
    not DSN, reason="set SCHEMASENTRY_TEST_DATABASE_URL to a disposable PostgreSQL test server"
)


@pytest.fixture(scope="module")
def corpus_database() -> Iterator[str]:
    assert DSN is not None
    name = f"ss_m3_{uuid.uuid4().hex}"
    with psycopg.connect(DSN, autocommit=True, connect_timeout=10) as connection:
        connection.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    started = time.perf_counter()
    try:
        yield make_conninfo(DSN, dbname=name)
    finally:
        with psycopg.connect(DSN, autocommit=True, connect_timeout=10) as connection:
            # The exact generated name was created above; no pre-existing database is removed.
            connection.execute(
                sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name))
            )
        elapsed = time.perf_counter() - started
        assert elapsed < 60, f"live M3 corpus took {elapsed:.2f}s (60s budget)"


def _capture(dsn: str, schema: str) -> Snapshot:
    return capture_snapshot(dsn, schemas=[schema], captured_at=CAPTURED_AT)


def _project(result: Any, expected: dict[str, Any]) -> list[dict[str, Any]]:
    fields = {"schema", "table", "object", "kind", "baseSeverity", "confidence"}
    selected = [f for f in result.findings if f.rule_id == expected["ruleId"]]
    items = []
    for finding in selected:
        payload = finding.model_dump(by_alias=True, mode="json")
        item = {key: payload[key] for key in fields}
        if any("effects" in f for f in expected["findings"]):
            item["effects"] = payload["effects"]
        items.append(item)
    return sorted(items, key=lambda f: (f["schema"], f["table"], f["object"], f["kind"]))


def _heap_file(connection: psycopg.Connection[Any], schema: str) -> int:
    row = connection.execute(
        "SELECT pg_relation_filenode(c.oid) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname = 'items'",
        (schema,),
    ).fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.parent.name)
def test_live_reviewed_m3_corpus(path: Path, corpus_database: str) -> None:
    expected = json.loads(path.read_text(encoding="utf-8"))
    if not expected["live"]:
        pytest.skip("reviewed offline-only legacy, contradictory or untested-version evidence")
    desired = load_snapshot(path.parent / "after.json")
    schema = desired.schemas[0]
    migration = load_migration(path.parent / "migration.sql")
    assert [s.status for s in migration.statements] == expected["statementStatuses"]
    with psycopg.connect(corpus_database, autocommit=True, connect_timeout=10) as connection:
        connection.execute("SET statement_timeout = '10s'")
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        try:
            connection.execute((path.parent / "before.sql").read_text(encoding="utf-8"))
            before = _capture(corpus_database, schema)
            heap_before = _heap_file(connection, schema) if "heapRewrite" in expected else None
            source = (path.parent / "migration.sql").read_text(encoding="utf-8")
            if expected["migrationError"]:
                with pytest.raises(psycopg.Error) as failed:
                    connection.execute(source)
                assert failed.value.sqlstate == expected["migrationError"]
                actual_after = _capture(corpus_database, schema)
                assert compare(before, actual_after).changes == []
                # Classify the explicitly desired schema after PostgreSQL rejected the statement.
                after = desired.model_copy(
                    update={"server_version": before.server_version, "database": before.database}
                )
            else:
                operations = [o for s in migration.statements for o in s.operations]
                if any(
                    o.kind == "vacuum_full" for o in operations
                ) or source.lstrip().upper().startswith("VACUUM"):
                    connection.execute(source)  # VACUUM must run outside an explicit transaction.
                else:
                    with connection.transaction():
                        connection.execute(source)
                        for operation in operations:
                            modes = connection.execute(
                                "SELECT mode FROM pg_locks WHERE pid = pg_backend_pid() "
                                "AND granted "
                                "AND relation = (SELECT c.oid FROM pg_class c JOIN pg_namespace n "
                                "ON n.oid = c.relnamespace WHERE n.nspname = %s "
                                "AND c.relname = %s)",
                                (schema, operation.table),
                            ).fetchall()
                            assert ("AccessExclusiveLock",) in modes
                after = _capture(corpus_database, schema)
            hint_file = path.parent / "hints.json"
            if expected["hintError"]:
                with pytest.raises((ValueError, ToolError), match=r"rename|hint"):
                    classify(before, after, migration=migration, hints=load_hints(hint_file))
                return
            hints = load_hints(hint_file) if hint_file.exists() else None
            result = classify(before, after, migration=migration, hints=hints)
            assert _project(result, expected) == expected["findings"]
            if heap_before is not None:
                rewritten = _heap_file(connection, schema) != heap_before
                assert rewritten == expected["heapRewrite"]
                effects = [f.effects for f in result.findings if f.rule_id == "SS005"]
                assert len(effects) == 1 and effects[0] is not None
                assert effects[0].rewrite == ("required" if rewritten else "not_required")
            if "fastDefault" in expected:
                operation = migration.statements[0].operations[0]
                row = connection.execute(
                    "SELECT a.atthasmissing FROM pg_attribute a "
                    "JOIN pg_class c ON c.oid = a.attrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = %s "
                    "AND c.relname = 'items' AND a.attname = %s",
                    (schema, operation.column),
                ).fetchone()
                assert row == (expected["fastDefault"],)
            if path.parent.name.startswith("0037-"):
                row = connection.execute(
                    sql.SQL("SELECT body FROM {}.items WHERE id = 1").format(sql.Identifier(schema))
                ).fetchone()
                assert row == ("old",)  # SET DEFAULT did not backfill the committed existing row.
        finally:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_vacuum_full_requests_access_exclusive(corpus_database: str) -> None:
    with (
        psycopg.connect(corpus_database, autocommit=True, connect_timeout=10) as worker,
        psycopg.connect(corpus_database, connect_timeout=10) as blocker,
        psycopg.connect(corpus_database, autocommit=True, connect_timeout=10) as observer,
    ):
        worker.execute("CREATE TABLE public.ss_m3_vacuum_lock (id integer)")
        worker.execute("INSERT INTO public.ss_m3_vacuum_lock VALUES (1)")
        worker.execute("SET statement_timeout = '10s'")
        worker.execute("SET lock_timeout = '8s'")
        row = worker.execute("SELECT pg_backend_pid()").fetchone()
        assert row is not None
        pid = row[0]
        blocker.execute("LOCK TABLE public.ss_m3_vacuum_lock IN ACCESS SHARE MODE")
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(worker.execute, "VACUUM FULL public.ss_m3_vacuum_lock")
            try:
                deadline = time.monotonic() + 5
                requested = False
                while time.monotonic() < deadline:
                    row = observer.execute(
                        "SELECT 1 FROM pg_locks WHERE pid = %s AND NOT granted "
                        "AND mode = 'AccessExclusiveLock' "
                        "AND relation = 'public.ss_m3_vacuum_lock'::regclass",
                        (pid,),
                    ).fetchone()
                    if row is not None:
                        requested = True
                        break
                    time.sleep(0.01)
                assert requested, "VACUUM FULL did not request the documented lock"
            finally:
                blocker.rollback()
            pending.result(timeout=10)


def test_catalog_volatility_allowlist_matches_server(corpus_database: str) -> None:
    expected = {
        "random": "v",
        "clock_timestamp": "v",
        "timeofday": "v",
        "now": "s",
        "transaction_timestamp": "s",
        "statement_timestamp": "s",
    }
    with psycopg.connect(corpus_database, autocommit=True, connect_timeout=10) as connection:
        rows = connection.execute(
            "SELECT p.proname, p.provolatile FROM pg_proc p JOIN pg_namespace n "
            "ON n.oid = p.pronamespace WHERE n.nspname = 'pg_catalog' "
            "AND p.pronargs = 0 AND p.proname = ANY(%s)",
            (list(expected),),
        ).fetchall()
        assert dict(rows) == expected
