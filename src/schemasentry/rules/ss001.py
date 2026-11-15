"""SS001: observed removed columns, including columns in removed tables."""

from schemasentry.evidence import Evidence, Finding, RuleMetadata
from schemasentry.rules._context import RuleContext, finding

METADATA = RuleMetadata(
    rule_id="SS001",
    title="Column removed",
    base_severity="critical",
    description="An observed removed column can break readers that still reference it.",
    safe_alternative="Stop reads/writes to the column, deploy that change, then drop it later.",
)


def evaluate(context: RuleContext) -> list[Finding]:
    paired = {(r.schema_name, r.table, r.from_column) for r in context.renames}
    result: list[Finding] = []
    for change in context.comparison.changes:
        if change.kind == "table_removed":
            columns = [
                c.name for c in context.before_tables[(change.schema_name, change.table)].columns
            ]
        elif change.kind == "column_removed":
            columns = [change.object]
        else:
            continue
        for column in sorted(columns):
            if (change.schema_name, change.table, column) in paired:
                continue
            result.append(
                finding(
                    METADATA,
                    change.schema_name,
                    change.table,
                    column,
                    "column_removed",
                    "high",
                    (
                        Evidence(
                            source="snapshot", detail="Column is present before and absent after."
                        ),
                    ),
                    ("Reader usage and data-preservation intent are not captured by snapshots.",),
                )
            )
    return result
