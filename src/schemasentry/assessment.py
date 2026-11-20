"""Pure immutable M4 assessment, scoring and explicit completeness/exit policy."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field

from schemasentry import __version__
from schemasentry.classification import classify
from schemasentry.diff import _validate
from schemasentry.errors import ToolError
from schemasentry.evidence import EvidenceModel, Finding, Notice, Severity
from schemasentry.hints import RenameHints
from schemasentry.m4_migration import AssessmentMigration
from schemasentry.m4_rules import evaluate_additional
from schemasentry.rules._m4_context import AssessmentContext
from schemasentry.snapshot import Snapshot, sort_snapshot, to_payload

LEVELS: tuple[Severity, ...] = ("low", "medium", "high", "critical")
MAX_OBJECTS = 200_000
MAX_FINDINGS = 10_000
MAX_NOTICES = 2_048
MAX_STRING_BYTES = 256 * 1024


class RiskModifier(EvidenceModel):
    name: Literal["row_estimate", "incoming_foreign_keys", "service_reader_lock"]
    status: Literal["applied", "not_applied", "unknown"]
    contribution: int = Field(ge=0, le=2)
    value: int | None = None
    evidence: str


class ScoredFinding(Finding):
    final_risk: Severity
    modifiers: tuple[RiskModifier, ...]
    estimated_seconds: None = None


class InputMetadata(EvidenceModel):
    schema_version: int
    catalog_evidence_version: Literal[1] | None
    dialect: str
    server_version: str
    captured_at: str
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class AssessmentNotice(Notice):
    impact: Literal["information", "incomplete"]


class Report(EvidenceModel):
    schema_version: Literal[1] = 1
    policy_version: Literal[1] = 1
    tool_version: str = __version__
    analysis_status: Literal["complete", "incomplete"]
    threshold: Severity
    overall_risk: Severity | None
    before: InputMetadata
    after: InputMetadata
    findings: tuple[ScoredFinding, ...]
    notices: tuple[AssessmentNotice, ...]
    limitations: tuple[str, ...]


def _object_limits(snapshot: Snapshot) -> int:
    stack: list[object] = [snapshot]
    count = 0
    while stack:
        value = stack.pop()
        if isinstance(value, BaseModel):
            count += 1
            stack.extend(getattr(value, name) for name in type(value).model_fields)
        elif isinstance(value, (list, tuple)):
            stack.extend(value)
        elif isinstance(value, str):
            try:
                if len(value.encode("utf-8")) > MAX_STRING_BYTES:
                    raise ToolError("M4 input contains an oversized dynamic string")
            except UnicodeError:
                raise ToolError("M4 input strings must be valid UTF-8") from None
        if count > MAX_OBJECTS:
            raise ToolError("M4 input exceeds its object bound")
    if snapshot.catalog_evidence is not None:
        count += sum(len(enum.labels) for enum in snapshot.catalog_evidence.enums)
    return count


def _metadata(snapshot: Snapshot) -> InputMetadata:
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    for chunk in encoder.iterencode(to_payload(snapshot)):
        digest.update(chunk.encode("utf-8"))
    return InputMetadata(
        schema_version=snapshot.schema_version,
        catalog_evidence_version=(
            snapshot.catalog_evidence.evidence_version if snapshot.catalog_evidence else None
        ),
        dialect=snapshot.dialect,
        server_version=snapshot.server_version,
        captured_at=snapshot.captured_at,
        digest=digest.hexdigest(),
    )


def score_finding(finding: Finding, before: Snapshot) -> ScoredFinding:
    table = next(
        (
            table
            for table in before.tables
            if (table.schema_name, table.name) == (finding.schema_name, finding.table)
        ),
        None,
    )
    rows = table.row_estimate if table else None
    size = 0 if rows is None or rows <= 1_000_000 else (1 if rows <= 20_000_000 else 2)
    catalog = before.catalog_evidence
    incoming = None
    if catalog is not None and table is not None:
        incoming = len(
            {
                (foreign.schema_name, foreign.table, foreign.name)
                for foreign in catalog.incoming_foreign_keys
                if (foreign.target_schema, foreign.target_table)
                == (finding.schema_name, finding.table)
            }
        )
    foreign = 1 if incoming is not None and incoming >= 2 else 0
    modifiers = (
        RiskModifier(
            name="row_estimate",
            status="unknown" if rows is None else ("applied" if size else "not_applied"),
            contribution=size,
            value=rows,
            evidence=(
                "Catalog rowEstimate is an estimate; mutually exclusive strict size tiers apply."
            ),
        ),
        RiskModifier(
            name="incoming_foreign_keys",
            status="unknown" if incoming is None else ("applied" if foreign else "not_applied"),
            contribution=foreign,
            value=incoming,
            evidence=(
                "Distinct incoming named FK constraints target this captured table"
                ", including outside-schema sources when known."
            ),
        ),
        RiskModifier(
            name="service_reader_lock",
            status="unknown",
            contribution=0,
            evidence="Reader ownership is unavailable under rename-hints v1.",
        ),
    )
    risk = LEVELS[min(3, LEVELS.index(finding.base_severity) + size + foreign)]
    return ScoredFinding(**finding.model_dump(by_alias=True), final_risk=risk, modifiers=modifiers)


INFORMATION_NOTICES = frozenset(
    {
        "migration_evidence_missing",
        "migration_evidence_empty",
        "not_valid_constraint_locks",
        "constraint_already_valid",
        "concurrent_index_caveats",
    }
)


def assess(
    before: Snapshot,
    after: Snapshot,
    *,
    migration: AssessmentMigration | None = None,
    hints: RenameHints | None = None,
    default_schema: str | None = "public",
    threshold: Severity = "high",
) -> Report:
    if threshold not in LEVELS:
        raise ValueError("unknown risk threshold")
    if _object_limits(before) + _object_limits(after) > MAX_OBJECTS:
        raise ToolError("M4 inputs exceed the combined object bound")
    before = sort_snapshot(Snapshot.model_validate(before.model_dump(by_alias=True)))
    after = sort_snapshot(Snapshot.model_validate(after.model_dump(by_alias=True)))
    _validate(before)
    _validate(after)
    for snapshot in (before, after):
        if any(
            len({c.ordinal for c in table.columns}) != len(table.columns)
            for table in snapshot.tables
        ):
            raise ToolError("M4 snapshot has duplicate column positions")
    context = AssessmentContext(before, after, migration, default_schema)
    additional, extra_notices = evaluate_additional(context)
    refine = bool(
        migration
        and context.confirmed
        and before.catalog_evidence is not None
        and after.catalog_evidence is not None
        and set(before.schemas) == set(after.schemas)
        and all(finding.confidence == "high" for finding in additional)
        and all(notice.kind in INFORMATION_NOTICES for notice in extra_notices)
        and all(notice.kind in INFORMATION_NOTICES for notice in migration.notices)
    )
    legacy = classify(
        before,
        after,
        migration=(migration.classification_view() if refine else migration.legacy)
        if migration
        else None,
        hints=hints,
        default_schema=default_schema,
    )
    superseded = set(migration.superseded_starts) if migration else set()
    notices = [
        notice
        for notice in legacy.notices
        if not (
            notice.kind in ("unanalysable_statement", "migration_parse_error")
            and notice.location
            and notice.location.start in superseded
        )
    ]
    findings = [*legacy.findings, *additional]
    notices.extend(extra_notices)
    if migration is not None:
        notices.extend(migration.notices)
    if set(before.schemas) != set(after.schemas):
        notices.append(
            Notice(kind="snapshot_scope_mismatch", detail="Before/after schema scopes differ.")
        )
    for name, snapshot in (("before", before), ("after", after)):
        catalog = snapshot.catalog_evidence
        if catalog is None:
            notices.append(
                Notice(
                    kind="catalog_evidence_missing",
                    detail=(
                        f"Required {name} M4 catalog evidence is unavailable; "
                        "legacy omission is not an empty enum catalog."
                    ),
                )
            )
            continue
        if catalog.unsupported_types or any(
            ref.mode == "domain" or ref.type_schema not in catalog.scope_schemas
            for ref in catalog.enum_columns
        ):
            notices.append(
                Notice(
                    kind="enum_dependency_unavailable",
                    detail=(
                        f"Some {name} enum/type dependencies are outside "
                        "the supported captured scope."
                    ),
                )
            )
    if any(finding.confidence == "low" for finding in findings):
        notices.append(
            Notice(
                kind="classification_evidence_incomplete",
                detail=(
                    "Required classification evidence is uncertain; confidence does no"
                    "t lower policy severity."
                ),
            )
        )
    if len(findings) > MAX_FINDINGS or len(notices) > MAX_NOTICES:
        raise ToolError("M4 assessment exceeds its finding or notice bound")
    findings.sort(
        key=lambda finding: (
            finding.schema_name,
            finding.table,
            finding.object,
            finding.rule_id,
            finding.kind,
            tuple(e.location.start if e.location else -1 for e in finding.evidence),
        )
    )
    scored = tuple(score_finding(finding, before) for finding in findings)
    unique = {notice.model_dump_json(): notice for notice in notices}
    ordered = sorted(
        unique.values(),
        key=lambda notice: (
            notice.location.start if notice.location else -1,
            notice.kind,
            notice.detail,
        ),
    )
    result_notices = tuple(
        AssessmentNotice(
            **notice.model_dump(by_alias=True),
            impact="information" if notice.kind in INFORMATION_NOTICES else "incomplete",
        )
        for notice in ordered
    )
    incomplete = any(notice.impact == "incomplete" for notice in result_notices)
    overall = max((finding.final_risk for finding in scored), key=LEVELS.index) if scored else None
    return Report(
        analysis_status="incomplete" if incomplete else "complete",
        threshold=threshold,
        overall_risk=overall,
        before=_metadata(before),
        after=_metadata(after),
        findings=scored,
        notices=result_notices,
        limitations=(
            (
                "The report compares supplied/observed schema states; migration SQ"
                "L is secondary requested evidence and is never executed or used t"
                "o predict an after snapshot."
            ),
            "Risk is policy, not a calibrated duration or proof of safety.",
            (
                "Reader ownership, uncaptured dependencies and calibrated estimate"
                "dSeconds are unavailable in M4."
            ),
        ),
    )


def report_exit(report: Report) -> int:
    if report.analysis_status == "incomplete":
        return 3
    if report.overall_risk == "critical":
        return 2
    if report.overall_risk is not None and LEVELS.index(report.overall_risk) >= LEVELS.index(
        report.threshold
    ):
        return 1
    return 0
