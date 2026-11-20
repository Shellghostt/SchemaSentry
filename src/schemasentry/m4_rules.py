"""Ten-rule M4 assessment surface, preserving the seven-rule M3 registry."""

from schemasentry.evidence import Finding, Notice, RuleMetadata
from schemasentry.rules import rule_metadata, ss008, ss009, ss010
from schemasentry.rules._m4_context import AssessmentContext


def public_rule_metadata() -> tuple[RuleMetadata, ...]:
    return (*rule_metadata(), ss008.METADATA, ss009.METADATA, ss010.METADATA)


def evaluate_additional(context: AssessmentContext) -> tuple[list[Finding], list[Notice]]:
    findings, notices = ss008.evaluate(context)
    index_findings, index_notices = ss009.evaluate(context)
    findings.extend(index_findings)
    notices.extend(index_notices)
    findings.extend(ss010.evaluate(context))
    if context.migration is not None:
        for statement in context.migration.legacy.statements:
            for legacy_operation in statement.operations:
                schema = legacy_operation.schema_name or context.default_schema
                if any(
                    (relation.schema_name, relation.table, relation.kind)
                    == (schema, legacy_operation.table, "partitioned")
                    for snapshot in (context.before, context.after)
                    if snapshot.catalog_evidence is not None
                    for relation in snapshot.catalog_evidence.relations
                ):
                    notices.append(
                        Notice(
                            kind="unsupported_relation_effects",
                            detail=(
                                "The legacy operation's ordinary-table effects are "
                                "unconfirmed for this partitioned relation."
                            ),
                            location=statement.location,
                        )
                    )
    for operation in context.operations:
        schema = context.schema(operation)
        if operation.kind in ("add_constraint", "validate_constraint", "create_index"):
            exists = bool(
                schema is not None
                and (
                    context.table(schema, operation.target)
                    or context.table(schema, operation.target, before=True)
                )
            )
        else:
            exists = schema is not None and any(
                (enum.schema_name, enum.name) == (schema, operation.target)
                for snapshot in (context.before, context.after)
                if snapshot.catalog_evidence is not None
                for enum in snapshot.catalog_evidence.enums
            )
        if not exists:
            notices.append(
                Notice(
                    kind="unresolved_m4_target",
                    detail="M4 SQL target is outside the declared snapshot scope.",
                    location=operation.location,
                )
            )
        if operation.kind in ("add_constraint", "validate_constraint") and schema is not None:
            table = context.table(schema, operation.target)
            constraint = (
                next((c for c in table.constraints if c.name == operation.name), None)
                if table is not None
                else None
            )
            if constraint is None or constraint.kind not in ("check", "foreign_key"):
                notices.append(
                    Notice(
                        kind="unresolved_m4_object",
                        detail=(
                            "The requested CHECK/FK constraint has no eligible "
                            "observed after object."
                        ),
                        location=operation.location,
                    )
                )
        if (
            operation.kind.startswith("enum_")
            and schema is not None
            and not context.enum_changes_match(schema, operation.target)
        ):
            notices.append(
                Notice(
                    kind="unconfirmed_m4_operation",
                    detail=(
                        "Requested enum operations do not match the observed catalog membership."
                    ),
                    location=operation.location,
                )
            )
        if not operation.simple:
            notices.append(
                Notice(
                    kind="unavailable_m4_syntax",
                    detail="Detailed operation variants are outside the supported M4 binding.",
                    location=operation.location,
                )
            )
        if operation.transaction in ("rolled_back", "unknown"):
            notices.append(
                Notice(
                    kind="unavailable_m4_transaction",
                    detail="Requested effects in this transaction context are not confirmed.",
                    location=operation.location,
                )
            )
    return findings, notices
