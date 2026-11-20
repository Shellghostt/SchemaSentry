"""Shared pure M4 state/evidence binding; no change to the M3 context."""

from __future__ import annotations

from dataclasses import dataclass

from schemasentry.evidence import Confidence, Evidence, Finding, RuleMetadata
from schemasentry.m4_migration import AssessmentMigration, AssessmentOperation
from schemasentry.rules._semantics import known_version
from schemasentry.snapshot import Snapshot, Table


@dataclass(frozen=True)
class AssessmentContext:
    before: Snapshot
    after: Snapshot
    migration: AssessmentMigration | None
    default_schema: str | None

    @property
    def confirmed(self) -> bool:
        return known_version(self.before.server_version, self.after.server_version)

    @property
    def operations(self) -> tuple[AssessmentOperation, ...]:
        return self.migration.operations if self.migration else ()

    def schema(self, operation: AssessmentOperation) -> str | None:
        return operation.schema_name if operation.schema_name is not None else self.default_schema

    def for_object(
        self, kind: str, schema: str, table: str, name: str | None = None
    ) -> tuple[AssessmentOperation, ...]:
        return tuple(
            operation
            for operation in self.operations
            if operation.kind == kind
            and self.schema(operation) == schema
            and operation.target == table
            and (name is None or operation.name == name)
        )

    def table(self, schema: str, name: str, *, before: bool = False) -> Table | None:
        snapshot = self.before if before else self.after
        return next(
            (
                table
                for table in snapshot.tables
                if (table.schema_name, table.name) == (schema, name)
            ),
            None,
        )

    def enum_operations(self, schema: str, name: str) -> tuple[AssessmentOperation, ...]:
        return tuple(
            operation
            for operation in self.operations
            if operation.kind.startswith("enum_")
            and self.schema(operation) == schema
            and operation.target == name
        )

    def enum_changes_match(self, schema: str, name: str) -> bool:
        """Bind the supported label requests to observed catalogs, without executing SQL."""
        if self.before.catalog_evidence is None or self.after.catalog_evidence is None:
            return False
        old = next(
            (
                e
                for e in self.before.catalog_evidence.enums
                if (e.schema_name, e.name) == (schema, name)
            ),
            None,
        )
        new = next(
            (
                e
                for e in self.after.catalog_evidence.enums
                if (e.schema_name, e.name) == (schema, name)
            ),
            None,
        )
        operations = self.enum_operations(schema, name)
        kinds = tuple(op.kind for op in operations)
        if kinds == ("enum_drop",):
            return old is not None and new is None
        if kinds == ("enum_create",):
            return old is None and new is not None and operations[0].labels == new.labels
        if kinds == ("enum_drop", "enum_create"):
            return old is not None and new is not None and operations[1].labels == new.labels
        if old is None or new is None or not operations:
            return False
        labels = list(old.labels)
        for operation in operations:
            if operation.kind == "enum_add":
                if operation.new_label is None or operation.new_label in labels:
                    return False
                labels.append(operation.new_label)
            elif operation.kind == "enum_rename":
                if (
                    operation.old_label not in labels
                    or operation.new_label is None
                    or operation.new_label in labels
                ):
                    return False
                labels[labels.index(operation.old_label)] = operation.new_label
            else:
                return False
        return tuple(labels) == new.labels

    def migration_evidence(self, operation: AssessmentOperation) -> Evidence:
        statement = (
            next(
                (
                    statement
                    for statement in self.migration.legacy.statements
                    if statement.location.start == operation.location.start
                ),
                None,
            )
            if self.migration
            else None
        )
        return Evidence(
            source="migration",
            detail=statement.text if statement else "Requested operation.",
            location=operation.location,
        )


def m4_finding(
    metadata: RuleMetadata,
    schema: str,
    table: str,
    name: str,
    kind: str,
    confidence: Confidence,
    evidence: tuple[Evidence, ...],
    limitations: tuple[str, ...],
) -> Finding:
    return Finding(
        rule_id=metadata.rule_id,
        schema=schema,
        table=table,
        object=name,
        kind=kind,
        base_severity=metadata.base_severity,
        confidence=confidence,
        evidence=evidence,
        limitations=limitations,
        safe_alternative=metadata.safe_alternative,
    )
