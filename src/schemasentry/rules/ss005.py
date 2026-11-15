"""SS005: conditional lock, scan and rewrite evidence from supported operations."""

from schemasentry.evidence import (
    Confidence,
    Effect,
    Effects,
    Evidence,
    Finding,
    LockLevel,
    RuleMetadata,
)
from schemasentry.rules._context import BoundOperation, RuleContext, finding
from schemasentry.rules._semantics import (
    column_type,
    default_nonnull,
    default_volatility,
    nonnull_proof,
)

METADATA = RuleMetadata(
    rule_id="SS005",
    title="Locking or rewriting statement",
    base_severity="high",
    description="Separate DDL locks, row scanning and heap rewriting; no duration guesses.",
    safe_alternative="Plan the DDL lock window; validate the table and server semantics.",
)


def _effects(context: RuleContext, bound: BoundOperation) -> tuple[Effects, Confidence]:
    lock: LockLevel = (
        "access_exclusive" if context.confirmed_version and bound.consistent else "unknown"
    )
    uncertain = Effects(lock_level=lock, scan="unknown", rewrite="unknown")
    if not context.simple(bound):
        return uncertain, "low"
    operation = bound.operation
    old, new = context.operation_columns(bound)
    if any(c.identity or c.generated is not None for c in (old, new) if c is not None):
        return uncertain, "low"
    if operation.kind == "vacuum_full":
        return Effects(lock_level=lock, scan="required", rewrite="required"), "high"
    if operation.kind in {
        "set_default",
        "drop_default",
        "drop_not_null",
        "rename_column",
        "drop_column",
    }:
        return Effects(lock_level=lock, scan="not_required", rewrite="not_required"), "high"
    if operation.kind == "set_not_null" and old is not None and new is not None:
        key = (bound.schema_name, operation.table)
        legacy = any(
            c.kind == "check" and c.definition is None
            for table in (context.before_tables[key], context.after_tables[key])
            for c in table.constraints
        )
        proved = not old.nullable or nonnull_proof(
            context.before_tables[key], context.after_tables[key], new.name
        )
        scan: Effect = "not_required" if proved else "unknown" if legacy else "required"
        return Effects(
            lock_level=lock, scan=scan, rewrite="not_required"
        ), "low" if legacy else "high"
    if operation.kind == "add_column" and new is not None and column_type(new) is not None:
        volatility = (
            default_volatility(operation.default, context.confirmed_version)
            if operation.default is not None
            else "nonvolatile"
        )
        if volatility == "nonvolatile":
            target = column_type(new)
            assert target is not None
            nonnull = default_nonnull(operation.default, target)
            if nonnull is None:
                return uncertain, "low"
            add_scan: Effect = "not_required" if new.nullable or nonnull else "required"
            return Effects(lock_level=lock, scan=add_scan, rewrite="not_required"), "high"
        if volatility == "volatile":
            return Effects(lock_level=lock, scan="required", rewrite="required"), "high"
        return uncertain, "low"
    if (
        operation.kind == "alter_type"
        and old is not None
        and new is not None
        and not operation.using
    ):
        a, b = column_type(old), column_type(new)
        if a is not None and b is not None:
            if a.family == b.family == "varchar":
                widening = not b.modifiers or (
                    bool(a.modifiers) and b.modifiers[0] >= a.modifiers[0]
                )
                effect: Effect = "not_required" if widening else "required"
                return Effects(lock_level=lock, scan=effect, rewrite=effect), "high"
            if (a.family, b.family) in {
                ("integer", "bigint"),
                ("bigint", "integer"),
                ("text", "varchar"),
            }:
                return Effects(lock_level=lock, scan="required", rewrite="required"), "high"
    return uncertain, "low"


def evaluate(context: RuleContext) -> list[Finding]:
    result: list[Finding] = []
    for bound in context.operations:
        operation = bound.operation
        effects, confidence = _effects(context, bound)
        result.append(
            finding(
                METADATA,
                bound.schema_name,
                operation.table,
                operation.new_column or operation.column or operation.table,
                operation.kind,
                confidence,
                (
                    Evidence(
                        source="migration",
                        detail=f"Declared supported operation: {operation.kind}.",
                        location=bound.statement.location,
                    ),
                    Evidence(
                        source="postgres_semantics",
                        detail="Confirmed effects require one matching operation on PG 13/15/16.",
                    ),
                ),
                (
                    "Parsed SQL declares an operation; execution and intent remain unproven.",
                    "Effects are conditional on the represented ordinary table and captured scope.",
                    "USING, interacting operations and unsupported evidence keep effects unknown.",
                    "Inheritance/partitions and lock durations are not captured or estimated.",
                ),
                effects,
            )
        )
    return result
