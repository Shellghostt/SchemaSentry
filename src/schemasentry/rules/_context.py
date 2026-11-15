"""Private immutable rule context built from validated, unmodified M2 inputs."""

from __future__ import annotations

from dataclasses import dataclass, replace

from schemasentry.diff import Comparison, compare
from schemasentry.evidence import Confidence, Effects, Evidence, Finding, Notice, RuleMetadata
from schemasentry.hints import ColumnRename, RenameHints, validate_hints
from schemasentry.migration import Migration, MigrationOperation, MigrationStatement, OperationKind
from schemasentry.rules._semantics import column_type, defaults_match, describe_type, known_version
from schemasentry.snapshot import Column, Snapshot, Table


@dataclass(frozen=True)
class ColumnPair:
    schema_name: str
    table: str
    before_table: Table
    after_table: Table
    before: Column | None
    after: Column | None

    @property
    def name(self) -> str:
        column = self.after if self.after is not None else self.before
        assert column is not None
        return column.name

    @property
    def renamed(self) -> bool:
        return bool(self.before and self.after and self.before.name != self.after.name)


@dataclass(frozen=True)
class BoundOperation:
    schema_name: str
    operation: MigrationOperation
    statement: MigrationStatement
    consistent: bool = False


@dataclass(frozen=True)
class RuleContext:
    before: Snapshot
    after: Snapshot
    comparison: Comparison
    renames: tuple[ColumnRename, ...]
    before_tables: dict[tuple[str, str], Table]
    after_tables: dict[tuple[str, str], Table]
    pairs: tuple[ColumnPair, ...]
    operations: tuple[BoundOperation, ...] = ()
    complete_evidence: bool = False

    @property
    def confirmed_version(self) -> bool:
        return known_version(self.before.server_version, self.after.server_version)

    def for_column(self, pair: ColumnPair, kind: OperationKind) -> tuple[BoundOperation, ...]:
        names = {c.name for c in (pair.before, pair.after) if c is not None}
        return tuple(
            bound
            for bound in self.operations
            if bound.schema_name == pair.schema_name
            and bound.operation.table == pair.table
            and bound.operation.column in names
            and bound.operation.kind == kind
        )

    def operation_columns(self, bound: BoundOperation) -> tuple[Column | None, Column | None]:
        operation = bound.operation
        key = (bound.schema_name, operation.table)
        left, right = self.before_tables.get(key), self.after_tables.get(key)
        old = next((c for c in left.columns if c.name == operation.column), None) if left else None
        new_name = operation.new_column if operation.kind == "rename_column" else operation.column
        new = next((c for c in right.columns if c.name == new_name), None) if right else None
        if operation.kind == "alter_type" and (old is None or new is None):
            pair = next(
                (
                    p
                    for p in self.pairs
                    if (p.schema_name, p.table) == key
                    and p.renamed
                    and any(c.name == operation.column for c in (p.before, p.after) if c)
                ),
                None,
            )
            if pair:
                return pair.before, pair.after
        return old, new

    def matches(self, bound: BoundOperation) -> bool:
        operation = bound.operation
        key = (bound.schema_name, operation.table)
        old, new = self.operation_columns(bound)
        if operation.kind == "vacuum_full":
            return key in self.before_tables and key in self.after_tables
        if operation.kind == "drop_column":
            return old is not None and new is None
        if operation.kind == "rename_column":
            return bool(
                old is not None
                and new is not None
                and key in self.before_tables
                and key in self.after_tables
                and all(c.name != operation.column for c in self.after_tables[key].columns)
                and all(c.name != operation.new_column for c in self.before_tables[key].columns)
            )
        if new is None:
            return False
        if operation.kind in {"add_column", "alter_type"}:
            target = describe_type(operation.target_type or "")
            if target is None or target != column_type(new):
                return False
            if operation.kind == "add_column":
                return (
                    old is None
                    and key in self.before_tables
                    and operation.nullable == new.nullable
                    and defaults_match(operation.default, new.default)
                )
            return old is not None
        if old is None:
            return False
        if operation.kind in {"set_default", "drop_default"}:
            return defaults_match(operation.default, new.default)
        if operation.kind == "set_not_null":
            return not new.nullable
        if operation.kind == "drop_not_null":
            return new.nullable
        return False

    def simple(self, bound: BoundOperation) -> bool:
        if not self.complete_evidence or not self.confirmed_version or not bound.consistent:
            return False
        if bound.operation.conditional:
            return False
        old, new = self.operation_columns(bound)
        if bound.operation.kind != "rename_column" and old and new and old.name != new.name:
            return False
        return (
            sum(
                b.schema_name == bound.schema_name and b.operation.table == bound.operation.table
                for b in self.operations
            )
            == 1
        )


def _pairs(
    old: dict[tuple[str, str], Table],
    new: dict[tuple[str, str], Table],
    renames: tuple[ColumnRename, ...],
) -> tuple[ColumnPair, ...]:
    result: list[ColumnPair] = []
    for schema, name in sorted(old.keys() & new.keys()):
        left, right = old[(schema, name)], new[(schema, name)]
        columns_before = {c.name: c for c in left.columns}
        columns_after = {c.name: c for c in right.columns}
        mappings = [r for r in renames if (r.schema_name, r.table) == (schema, name)]
        suppressed = {r.from_column for r in mappings} | {r.to_column for r in mappings}
        for column in sorted((columns_before.keys() | columns_after.keys()) - suppressed):
            result.append(
                ColumnPair(
                    schema, name, left, right, columns_before.get(column), columns_after.get(column)
                )
            )
        for rename in mappings:
            result.append(
                ColumnPair(
                    schema,
                    name,
                    left,
                    right,
                    columns_before[rename.from_column],
                    columns_after[rename.to_column],
                )
            )
    return tuple(sorted(result, key=lambda pair: (pair.schema_name, pair.table, pair.name)))


def build_context(
    before: Snapshot,
    after: Snapshot,
    migration: Migration | None,
    hints: RenameHints | None,
    default_schema: str | None,
) -> tuple[RuleContext, list[Notice]]:
    comparison = compare(before, after)
    renames = validate_hints(hints, before, after)
    old = {(t.schema_name, t.name): t for t in before.tables}
    new = {(t.schema_name, t.name): t for t in after.tables}
    context = RuleContext(before, after, comparison, renames, old, new, _pairs(old, new, renames))
    notices = [Notice(kind="legacy_snapshot_evidence", detail=w) for w in comparison.warnings]
    if not context.confirmed_version:
        notices.append(
            Notice(
                kind="server_version_evidence_unconfirmed",
                detail="Confirmed operation effects require matching PostgreSQL 13/15/16 versions.",
            )
        )
    if default_schema is not None and (not isinstance(default_schema, str) or not default_schema):
        raise ValueError("default_schema must be a nonempty schema name")
    if migration is None:
        notices.append(
            Notice(
                kind="migration_evidence_missing",
                detail="Snapshots show state changes; executed SQL and effects remain unproven.",
            )
        )
        return context, notices
    for error in migration.errors:
        notices.append(
            Notice(kind="migration_parse_error", detail=error.detail, location=error.location)
        )
    if not migration.statements and not migration.errors:
        notices.append(
            Notice(kind="migration_evidence_empty", detail="No SQL statements supplied.")
        )
    operations: list[BoundOperation] = []
    count = 0
    for statement in migration.statements:
        if statement.status != "supported":
            notices.append(
                Notice(
                    kind="unanalysable_statement",
                    detail=statement.detail or "Statement evidence is unavailable.",
                    location=statement.location,
                )
            )
            continue
        for operation in statement.operations:
            count += 1
            schema = operation.schema_name if operation.schema_name is not None else default_schema
            if schema is None or (schema, operation.table) not in old.keys() | new.keys():
                notices.append(
                    Notice(
                        kind="unresolved_statement_target",
                        detail="Bind unqualified targets explicitly and capture their table scope.",
                        location=statement.location,
                    )
                )
                continue
            bound = BoundOperation(schema, operation, statement)
            bound = replace(bound, consistent=context.matches(bound))
            operations.append(bound)
            if not bound.consistent:
                notices.append(
                    Notice(
                        kind="statement_snapshot_evidence_unconfirmed",
                        detail="Both snapshots do not prove the declared target/type/default.",
                        location=statement.location,
                    )
                )
    context = replace(
        context,
        operations=tuple(operations),
        complete_evidence=bool(migration.statements)
        and not migration.errors
        and all(s.status == "supported" for s in migration.statements)
        and len(operations) == count
        and all(b.consistent for b in operations),
    )
    return context, notices


def finding(
    metadata: RuleMetadata,
    schema: str,
    table: str,
    object_name: str,
    kind: str,
    confidence: Confidence,
    evidence: tuple[Evidence, ...],
    limitations: tuple[str, ...],
    effects: Effects | None = None,
) -> Finding:
    return Finding(
        rule_id=metadata.rule_id,
        schema=schema,
        table=table,
        object=object_name,
        kind=kind,
        base_severity=metadata.base_severity,
        confidence=confidence,
        evidence=evidence,
        limitations=limitations,
        safe_alternative=metadata.safe_alternative,
        effects=effects,
    )
