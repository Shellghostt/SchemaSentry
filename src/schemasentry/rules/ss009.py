"""SS009: index build mode, explicit transaction and partition restrictions."""

from schemasentry.evidence import Effects, Evidence, Finding, Notice, RuleMetadata
from schemasentry.rules._m4_context import AssessmentContext, m4_finding

METADATA = RuleMetadata(
    rule_id="SS009",
    title="Index creation blocks writes",
    base_severity="high",
    description=(
        "Ordinary index builds block writes; concurrent builds have explic"
        "it transaction and partition restrictions."
    ),
    safe_alternative=(
        "Consider CREATE INDEX CONCURRENTLY for a supported ordinary table"
        " outside an explicit transaction. It has multiple phases, lock wa"
        "its and possible invalid-index cleanup. For partitioned parents, "
        "review supported leaf-build/attach procedures; this is not univer"
        "sally lock-free."
    ),
)


def evaluate(context: AssessmentContext) -> tuple[list[Finding], list[Notice]]:
    findings: list[Finding] = []
    notices: list[Notice] = []
    candidates: set[tuple[str, str, str]] = set()
    for after_table in context.after.tables:
        prior = context.table(after_table.schema_name, after_table.name, before=True)
        names = {index.name for index in prior.indexes} if prior else set()
        candidates.update(
            (after_table.schema_name, after_table.name, index.name)
            for index in after_table.indexes
            if index.name not in names
        )
    for requested in context.operations:
        schema = context.schema(requested)
        if requested.kind == "create_index" and schema is not None and requested.name is not None:
            candidates.add((schema, requested.target, requested.name))
    for schema, name, index_name in sorted(candidates):
        table = context.table(schema, name)
        prior = context.table(schema, name, before=True)
        operations = context.for_object("create_index", schema, name, index_name)
        operation = operations[0] if len(operations) == 1 else None
        if table is None and prior is None:
            continue
        evidence: tuple[Evidence, ...] = (
            Evidence(
                source="snapshot",
                detail=f"Index target is {schema!r}.{name!r}, index {index_name!r}.",
            ),
        )
        if operation is not None:
            evidence += (context.migration_evidence(operation),)
        limitations = (
            "SQL is requested evidence, not proof of execution.",
            "No calibrated build duration is available.",
            (
                "Concurrent builds can fail leaving an invalid index; their multip"
                "le phases and lock waits still matter."
            ),
        )
        if (
            operation is not None
            and operation.concurrent
            and operation.transaction in ("explicit", "rolled_back")
        ):
            findings.append(
                m4_finding(
                    METADATA.model_copy(update={"base_severity": "critical"}),
                    schema,
                    name,
                    index_name,
                    "concurrent_index_in_transaction",
                    "high" if context.confirmed else "low",
                    evidence,
                    (
                        *limitations,
                        "CREATE INDEX CONCURRENTLY cannot execute inside an explicit trans"
                        "action block.",
                    ),
                )
            )
            continue
        catalog = context.after.catalog_evidence
        relation = (
            next(
                (
                    relation
                    for relation in catalog.relations
                    if (relation.schema_name, relation.table) == (schema, name)
                ),
                None,
            )
            if catalog
            else None
        )
        if (
            operation is not None
            and operation.concurrent
            and relation is not None
            and relation.kind == "partitioned"
        ):
            findings.append(
                m4_finding(
                    METADATA.model_copy(update={"base_severity": "critical"}),
                    schema,
                    name,
                    index_name,
                    "concurrent_partitioned_index_unsupported",
                    "high" if context.confirmed else "low",
                    evidence,
                    (*limitations, "A partitioned parent cannot be built concurrently directly."),
                )
            )
            continue
        index = (
            next((index for index in table.indexes if index.name == index_name), None)
            if table
            else None
        )
        old_names = {index.name for index in prior.indexes} if prior else set()
        known = bool(
            operation
            and context.confirmed
            and operation.simple
            and operation.transaction != "rolled_back"
            and relation
            and relation.kind == "ordinary"
            and index
            and index_name not in old_names
            and index.valid
            and index.method == "btree"
            and index.keys is not None
            and index.expression is None
            and index.predicate is None
            and not index.included_columns
            and tuple(index.columns) == operation.columns
            and index.unique == operation.unique
        )
        if known and operation is not None and operation.concurrent:
            notices.append(
                Notice(
                    kind="concurrent_index_caveats",
                    detail=(
                        "A supported concurrent build avoids ordinary write blocking but r"
                        "etains multiple phases, lock waits and invalid-index cleanup requ"
                        "irements."
                    ),
                    location=operation.location,
                )
            )
            continue
        finding = m4_finding(
            METADATA,
            schema,
            name,
            index_name,
            "index_build_blocks_writes" if known else "index_build_context_unknown",
            "high" if known else "low",
            evidence,
            (
                *limitations,
                "Expression/opclass/storage variants outside the supported binding"
                " remain uncertain.",
            ),
        )
        if known:
            finding = finding.model_copy(
                update={
                    "effects": Effects(lock_level="share", scan="required", rewrite="not_required")
                }
            )
        findings.append(finding)
    return findings, notices
