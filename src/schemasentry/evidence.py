"""Immutable internal M3 evidence. Public reports and risk scoring belong to M4."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

Severity = Literal["low", "medium", "high", "critical"]
Confidence = Literal["high", "low"]
Effect = Literal["required", "not_required", "unknown"]
LockLevel = Literal[
    "access_exclusive", "share", "share_row_exclusive", "share_update_exclusive", "unknown"
]


class EvidenceModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        serialize_by_alias=True,
        extra="forbid",
        frozen=True,
    )


class SourceLocation(EvidenceModel):
    """Character offsets are zero-based, end-exclusive; line/column are one-based."""

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    line: int = Field(ge=1)
    column: int = Field(ge=1)


class Evidence(EvidenceModel):
    source: Literal["snapshot", "migration", "hint", "postgres_semantics"]
    detail: str
    location: SourceLocation | None = None


class Effects(EvidenceModel):
    lock_level: LockLevel
    scan: Effect
    rewrite: Effect


class Finding(EvidenceModel):
    rule_id: str
    schema_name: str = Field(alias="schema")
    table: str
    object: str
    kind: str
    base_severity: Severity
    confidence: Confidence
    evidence: tuple[Evidence, ...]
    limitations: tuple[str, ...]
    safe_alternative: str | None = None
    effects: Effects | None = None


class Notice(EvidenceModel):
    kind: str
    detail: str
    location: SourceLocation | None = None


class Classification(EvidenceModel):
    findings: tuple[Finding, ...]
    notices: tuple[Notice, ...]


class RuleMetadata(EvidenceModel):
    rule_id: str
    title: str
    base_severity: Severity
    description: str
    safe_alternative: str | None = None
