"""SS010: known enum label/type removal and exact requested value rename."""

from schemasentry.evidence import Evidence, Finding, RuleMetadata
from schemasentry.rules._m4_context import AssessmentContext, m4_finding

METADATA = RuleMetadata(
    rule_id="SS010",
    title="Enum membership removed or renamed",
    base_severity="critical",
    description=(
        "Known removed enum membership or type identity can invalidate sto"
        "red/application values; an exact rename remains an application co"
        "mpatibility change."
    ),
    safe_alternative=(
        "Coordinate application readers and inspect dependent objects. Pos"
        "tgreSQL has no direct DROP VALUE; a replacement type/rebuild requ"
        "ires an explicit value mapping and migration plan. Label rename i"
        "s supported but can affect string consumers."
    ),
)


def evaluate(context: AssessmentContext) -> list[Finding]:
    before, after = context.before.catalog_evidence, context.after.catalog_evidence
    if before is None or after is None:
        return []
    old = {(enum.schema_name, enum.name): enum for enum in before.enums}
    new = {(enum.schema_name, enum.name): enum for enum in after.enums}
    findings: list[Finding] = []
    for (schema, name), enum in sorted(old.items()):
        replacement = new.get((schema, name))
        removed = tuple(
            label for label in enum.labels if replacement is None or label not in replacement.labels
        )
        if replacement is not None and not removed:
            continue
        operations = context.enum_operations(schema, name)
        rename = next(
            (
                operation
                for operation in operations
                if operation.kind == "enum_rename"
                and replacement is not None
                and all(op.kind in ("enum_add", "enum_rename") for op in operations)
                and context.enum_changes_match(schema, name)
                and operation.transaction != "rolled_back"
            ),
            None,
        )
        kind = (
            "enum_label_renamed"
            if rename
            else ("enum_type_removed" if replacement is None else "enum_labels_removed")
        )
        metadata = METADATA.model_copy(update={"base_severity": "high"}) if rename else METADATA
        refs = tuple(
            ref for ref in before.enum_columns if (ref.type_schema, ref.type_name) == (schema, name)
        )
        columns = tuple((ref.schema_name, ref.table, ref.column, ref.mode) for ref in refs)
        evidence: tuple[Evidence, ...] = (
            Evidence(
                source="snapshot",
                detail=(
                    f"Before enum labels: {enum.labels!r}; "
                    f"after: {replacement.labels if replacement else None!r}."
                ),
            ),
            Evidence(
                source="snapshot",
                detail=(f"Captured column references: {columns!r}."),
            ),
        )
        evidence += tuple(context.migration_evidence(operation) for operation in operations)
        findings.append(
            m4_finding(
                metadata,
                schema,
                "",
                name,
                kind,
                "high" if context.confirmed else "low",
                evidence,
                (
                    (
                        "Enum identity is qualified name; database-local OIDs are not cros"
                        "s-capture identity."
                    ),
                    (
                        "Captured column references do not cover uncaptured schemas or app"
                        "lication string consumers."
                    ),
                    (
                        "Removal/rebuild does not establish a successful data mapping; no "
                        "duration is estimated."
                    ),
                ),
            )
        )
    return findings
