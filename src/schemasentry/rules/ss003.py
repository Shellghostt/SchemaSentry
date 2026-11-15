"""SS003: defaults are never proof about historical NULL values."""

from schemasentry.evidence import Evidence, Finding, RuleMetadata
from schemasentry.rules._context import RuleContext, finding
from schemasentry.rules._semantics import nonnull_proof

METADATA = RuleMetadata(
    rule_id="SS003",
    title="NOT NULL added without validated evidence",
    base_severity="high",
    description="Historical rows may need checking; defaults do not prove nonnull rows.",
    safe_alternative=(
        "Add CHECK (column IS NOT NULL) NOT VALID under ACCESS EXCLUSIVE. "
        "It then checks new writes. "
        "Validate it under SHARE UPDATE EXCLUSIVE, which permits ordinary DML. SET NOT NULL still "
        "takes ACCESS EXCLUSIVE and may use the validated proof on PostgreSQL 13/15/16. "
        "Check inheritance/partition scope; this sequence is not lock-free."
    ),
)


def evaluate(context: RuleContext) -> list[Finding]:
    result: list[Finding] = []
    for pair in context.pairs:
        if pair.after is None or pair.after.nullable or (pair.before and not pair.before.nullable):
            continue
        operations = context.for_column(pair, "set_not_null")
        if (
            pair.before is not None
            and not pair.renamed
            and len(operations) == 1
            and context.simple(operations[0])
            and nonnull_proof(pair.before_table, pair.after_table, pair.name)
        ):
            continue
        legacy = any(
            c.kind == "check" and c.definition is None
            for table in (pair.before_table, pair.after_table)
            for c in table.constraints
        )
        result.append(
            finding(
                METADATA,
                pair.schema_name,
                pair.table,
                pair.name,
                "not_null_added",
                "low" if legacy or not context.confirmed_version else "high",
                (
                    Evidence(source="snapshot", detail="The resulting column is newly NOT NULL."),
                    Evidence(
                        source="snapshot",
                        detail="No retained, validated local CHECK proof established.",
                    ),
                ),
                (
                    "Defaults do not prove historical nonnull rows, including for an added column.",
                    "Row contents, inheritance and partition coverage are not captured.",
                ),
            )
        )
    return result
