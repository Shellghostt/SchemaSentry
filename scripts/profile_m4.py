"""Measure owned 500-table capture and repeat M4 assessment/output lifecycles with RSS."""

from __future__ import annotations

import argparse
import gc
import json
import os
import platform
import sys
import time
import tracemalloc
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
from profile_m3 import memory
from psycopg import sql
from psycopg.conninfo import make_conninfo

from schemasentry.assessment import MAX_STRING_BYTES, assess
from schemasentry.diff import compare, comparison_json, load_snapshot
from schemasentry.errors import ToolError
from schemasentry.hints import RenameHints, load_hints
from schemasentry.introspect import capture_snapshot
from schemasentry.m4_migration import parse_assessment_migration
from schemasentry.report import report_json, report_markdown
from schemasentry.snapshot import Snapshot, to_json

ROOT = Path(__file__).resolve().parents[1]
CAPTURED_AT = "2026-11-20T00:00:00Z"
Case = tuple[Snapshot, Snapshot, str, RenameHints | None]


def cases() -> tuple[Case, ...]:
    result = []
    for directory in (ROOT / "tests/corpus", ROOT / "tests/corpus-m4"):
        for oracle in sorted(directory.glob("*/expected.json")):
            expected = json.loads(oracle.read_text("utf-8"))
            if expected.get("hintError"):
                continue
            folder = oracle.parent
            hints = folder / "hints.json"
            result.append(
                (
                    load_snapshot(folder / "before.json"),
                    load_snapshot(folder / "after.json"),
                    (folder / "migration.sql").read_text("utf-8"),
                    load_hints(hints) if hints.is_file() else None,
                )
            )
    return tuple(result)


def lifecycle(case: Case) -> int:
    before, after, source, hints = case
    to_json(before)
    to_json(after)
    comparison_json(compare(before, after))
    report = assess(before, after, migration=parse_assessment_migration(source), hints=hints)
    report_json(report)
    report_markdown(report)
    assert all(f.estimated_seconds is None for f in report.findings)
    return len(report.findings)


def batch(inputs: tuple[Case, ...]) -> int:
    return sum(lifecycle(case) for case in inputs)


@contextmanager
def large_case(dsn: str, output: Path) -> Iterator[tuple[Case, dict[str, Any]]]:
    """Execute only generated synthetic setup in the exact database created by this run."""
    name = "ss_m4_perf_" + uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    owned_dsn = make_conninfo(dsn, dbname=name)
    try:
        with psycopg.connect(owned_dsn, autocommit=True, connect_timeout=10) as connection:
            connection.execute("SET statement_timeout='10s'")
            connection.execute("CREATE TYPE public.state AS ENUM ('draft','ready')")
            for index in range(500):
                table = sql.Identifier(f"t_{index:04d}")
                connection.execute(
                    sql.SQL(
                        "CREATE TABLE public.{} (id bigint PRIMARY KEY, amount integer NOT NULL, "
                        "note text, state public.state)"
                    ).format(table)
                )
                connection.execute(
                    sql.SQL(
                        "INSERT INTO public.{} SELECT g,g+1,'synthetic','ready'::public.state "
                        "FROM generate_series(0,99) g"
                    ).format(table)
                )
                connection.execute(sql.SQL("ANALYZE public.{}").format(table))
            connection.execute("CREATE SCHEMA outside")
            connection.execute(
                "CREATE TABLE outside.refs (a bigint REFERENCES public.t_0000(id), "
                "b bigint REFERENCES public.t_0000(id))"
            )
            metrics: dict[str, Any] = {"tables": 500, "rowsPerTable": 100}
            started = time.perf_counter()
            before = capture_snapshot(
                owned_dsn, schemas=["public"], captured_at=CAPTURED_AT, analysis_evidence=True
            )
            metrics["captureBeforeSeconds"] = time.perf_counter() - started
            statements = []
            for index in range(20):
                statements.append(
                    f"ALTER TABLE public.t_{index:04d} ADD CONSTRAINT amount_positive "
                    "CHECK (amount > 0);"
                )
            for index in range(20, 40):
                statements.append(
                    f"CREATE INDEX amount_idx_{index:04d} ON public.t_{index:04d}(amount);"
                )
            for index in range(40, 60):
                statements.append(f"ALTER TABLE public.t_{index:04d} DROP COLUMN note;")
            statements.append("ALTER TYPE public.state RENAME VALUE 'ready' TO 'done';")
            for statement in statements:
                connection.execute(statement)
            source = "\n".join(statements)
            started = time.perf_counter()
            after = capture_snapshot(
                owned_dsn, schemas=["public"], captured_at=CAPTURED_AT, analysis_evidence=True
            )
            metrics["captureAfterSeconds"] = time.perf_counter() - started
        metrics["serverVersion"] = before.server_version
        for label, snapshot in (("before", before), ("after", after)):
            started = time.perf_counter()
            text = to_json(snapshot)
            metrics[f"{label}SerializeSeconds"] = time.perf_counter() - started
            metrics[f"{label}SnapshotBytes"] = len(text.encode("utf-8"))
            (output / f"large-{label}.json").write_bytes(text.encode("utf-8"))
        started = time.perf_counter()
        comparison_json(compare(before, after))
        metrics["diffSeconds"] = time.perf_counter() - started
        started = time.perf_counter()
        report = assess(before, after, migration=parse_assessment_migration(source))
        metrics["assessmentSeconds"] = time.perf_counter() - started
        assert report.analysis_status == "complete" and len(report.findings) == 81
        metrics["findings"] = len(report.findings)
        for label, renderer, suffix in (
            ("json", report_json, "json"),
            ("markdown", report_markdown, "md"),
        ):
            started = time.perf_counter()
            text = renderer(report)
            metrics[f"{label}Seconds"] = time.perf_counter() - started
            metrics[f"{label}Bytes"] = len(text.encode("utf-8"))
            (output / f"large-report.{suffix}").write_bytes(text.encode("utf-8"))
        yield (before, after, source, None), metrics
    finally:
        with psycopg.connect(dsn, autocommit=True, connect_timeout=10) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def measure(inputs: tuple[Case, ...], large: Case, args: argparse.Namespace) -> None:
    started = time.perf_counter()
    batch(inputs)
    corpus_seconds = time.perf_counter() - started
    batch(inputs)
    lifecycle(large)
    gc.collect()
    baseline_memory = memory()
    print(
        json.dumps(
            {
                "python": sys.version.split()[0],
                "platform": sys.platform,
                "machine": platform.machine(),
                "logicalProcessors": os.cpu_count(),
                "corpusCases": len(inputs),
                "warmCorpusSeconds": corpus_seconds,
                "baselineMemory": baseline_memory,
            }
        ),
        flush=True,
    )
    tracemalloc.start()
    baseline = tracemalloc.take_snapshot()
    samples = []
    for cycle in range(args.cycles):
        tracemalloc.reset_peak()
        started = time.perf_counter()
        count = sum(batch(inputs) for _ in range(args.batches)) + lifecycle(large)
        oversized = large[0].model_copy(update={"database": "x" * (MAX_STRING_BYTES + 1)})
        try:
            assess(oversized, large[1])
        except ToolError:
            pass
        else:
            raise AssertionError("oversized input was accepted")
        del oversized
        gc.collect()
        retained, peak = tracemalloc.get_traced_memory()
        sample = {
            "cycle": cycle + 1,
            "lifecycles": len(inputs) * args.batches + 1,
            "findings": count,
            "seconds": time.perf_counter() - started,
            "retainedPythonBytes": retained,
            "peakPythonBytes": peak,
            **memory(),
        }
        samples.append(sample)
        print(json.dumps(sample), flush=True)
    final = tracemalloc.take_snapshot()
    growth = [
        {
            "file": str(stat.traceback[0].filename),
            "line": stat.traceback[0].lineno,
            "bytes": stat.size_diff,
            "objects": stat.count_diff,
        }
        for stat in final.compare_to(baseline, "lineno")[:8]
    ]
    tracemalloc.stop()
    print(json.dumps({"samples": samples, "largestRetainedDifferences": growth}), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=6)
    parser.add_argument("--batches", type=int, default=3)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist/m4-profile")
    args = parser.parse_args()
    if not 1 <= args.cycles <= 50 or not 1 <= args.batches <= 20:
        parser.error("cycles must be 1-50 and batches 1-20")
    dsn = os.environ.get("SCHEMASENTRY_TEST_DATABASE_URL")
    if not dsn:
        parser.error(
            "set SCHEMASENTRY_TEST_DATABASE_URL to a disposable server with CREATE DATABASE"
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    inputs = cases()
    with large_case(dsn, args.output_dir) as (large, metrics):
        print(json.dumps({"largeWorkload": metrics}), flush=True)
        assert metrics["captureBeforeSeconds"] < 5 and metrics["captureAfterSeconds"] < 5
        assert metrics["diffSeconds"] < 10
        measure(inputs, large, args)
        assert memory()["peakRssBytes"] < 300_000_000


if __name__ == "__main__":
    main()
