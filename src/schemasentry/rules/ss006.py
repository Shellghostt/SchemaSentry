"""SS006: validated one-to-one rename declarations, without proof of data copying."""

from schemasentry.evidence import Evidence, Finding, RuleMetadata
from schemasentry.rules._context import RuleContext, finding

METADATA = RuleMetadata(
    rule_id="SS006",
    title="Column rename declared",
    base_severity="high",
    description="A validated hint pairs observed drop/add endpoints inside classification only.",
    safe_alternative="Coordinate readers/writers, or use expand/contract with a backfill.",
)


def evaluate(context: RuleContext) -> list[Finding]:
    return [
        finding(
            METADATA,
            rename.schema_name,
            rename.table,
            rename.to_column,
            "column_rename_declared",
            "high",
            (
                Evidence(
                    source="hint",
                    detail=f"Validated hint: {rename.from_column!r} to {rename.to_column!r}.",
                ),
            ),
            (
                "Hints declare intent, not preservation of data or reader compatibility.",
                "Structural diff still reports drop/add; paired attributes remain classified.",
            ),
        )
        for rename in context.renames
    ]
