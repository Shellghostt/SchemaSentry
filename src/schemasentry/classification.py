"""Pure M3 library classification; the M2 structural diff and CLI stay unchanged."""

from __future__ import annotations

from schemasentry.evidence import Classification
from schemasentry.hints import RenameHints
from schemasentry.migration import Migration
from schemasentry.rules import evaluate
from schemasentry.rules._context import build_context
from schemasentry.snapshot import Snapshot


def classify(
    before: Snapshot,
    after: Snapshot,
    *,
    migration: Migration | None = None,
    hints: RenameHints | None = None,
    default_schema: str | None = None,
) -> Classification:
    context, notices = build_context(before, after, migration, hints, default_schema)
    findings = evaluate(context)
    findings.sort(
        key=lambda f: (
            f.schema_name,
            f.table,
            f.object,
            f.rule_id,
            f.kind,
            tuple(e.location.start if e.location else -1 for e in f.evidence),
        )
    )
    unique_notices = {notice.model_dump_json(): notice for notice in notices}
    ordered_notices = sorted(
        unique_notices.values(),
        key=lambda n: (n.location.start if n.location else -1, n.kind, n.detail),
    )
    return Classification(findings=tuple(findings), notices=tuple(ordered_notices))
