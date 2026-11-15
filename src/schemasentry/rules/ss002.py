"""SS002: type policy separated from conditional conversion effects."""

from schemasentry.evidence import Confidence, Evidence, Finding, RuleMetadata, Severity
from schemasentry.rules._context import ColumnPair, RuleContext, finding
from schemasentry.rules._semantics import column_type

METADATA = RuleMetadata(
    rule_id="SS002",
    title="Column type changed",
    base_severity="high",
    description="Classify the reviewed type matrix; unknown casts and typmods remain uncertain.",
    safe_alternative="Validate values and readers; use a separate column/backfill if needed.",
)


def _policy(context: RuleContext, pair: ColumnPair) -> tuple[Severity, Confidence] | None:
    assert pair.before is not None and pair.after is not None
    old, new = column_type(pair.before), column_type(pair.after)
    operations = context.for_column(pair, "alter_type")
    if (
        not context.confirmed_version
        or old is None
        or new is None
        or pair.before.identity
        or pair.after.identity
        or pair.before.generated is not None
        or pair.after.generated is not None
        or any(b.operation.using or b.operation.conditional or not b.consistent for b in operations)
    ):
        return "high", "low"
    if old.family == new.family == "varchar":
        widening = not new.modifiers or (
            bool(old.modifiers) and new.modifiers[0] >= old.modifiers[0]
        )
        if widening:
            if len(operations) == 1 and context.simple(operations[0]):
                return None
            return "high", "low"
        return "high", "high"
    if (old.family, new.family) == ("integer", "bigint"):
        return "medium", "high"
    if (old.family, new.family) in {
        ("bigint", "integer"),
        ("text", "varchar"),
        ("timestamp", "timestamptz"),
    }:
        return "high", "high"
    if (
        old.family == new.family == "numeric"
        and old.modifiers
        and new.modifiers
        and new.modifiers[1] >= old.modifiers[1]
        and new.modifiers[0] - new.modifiers[1] >= old.modifiers[0] - old.modifiers[1]
    ):
        return "medium", "high"
    return "high", "low"


def evaluate(context: RuleContext) -> list[Finding]:
    result: list[Finding] = []
    for pair in context.pairs:
        old, new = pair.before, pair.after
        if (
            old is None
            or new is None
            or (
                old.type == new.type
                and old.normalised_type == new.normalised_type
                and old.length == new.length
            )
        ):
            continue
        policy = _policy(context, pair)
        if policy is None:
            continue
        severity, confidence = policy
        result.append(
            finding(
                METADATA.model_copy(update={"base_severity": severity}),
                pair.schema_name,
                pair.table,
                pair.name,
                "column_type_changed",
                confidence,
                (
                    Evidence(
                        source="snapshot", detail=f"Type changed from {old.type!r} to {new.type!r}."
                    ),
                ),
                (
                    "Severity is policy; SQL casts, values and effects need separate evidence.",
                    "Confirmed semantics are limited to matching PostgreSQL 13/15/16 versions.",
                ),
            )
        )
    return result
