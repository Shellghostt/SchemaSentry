"""Optional versioned M4 catalog facts; absence is unknown, never an empty catalog."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from schemasentry.errors import ToolError

if TYPE_CHECKING:
    from schemasentry.snapshot import Snapshot


class CatalogModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, frozen=True, extra="forbid"
    )


class RelationFact(CatalogModel):
    schema_name: str = Field(alias="schema", min_length=1)
    table: str = Field(min_length=1)
    kind: Literal["ordinary", "partitioned"]


class ConstraintValidity(CatalogModel):
    schema_name: str = Field(alias="schema", min_length=1)
    table: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: Literal["check", "foreign_key"]
    validated: bool = Field(strict=True)


class EnumDefinition(CatalogModel):
    schema_name: str = Field(alias="schema", min_length=1)
    name: str = Field(min_length=1)
    labels: tuple[str, ...]

    @model_validator(mode="after")
    def unique_labels(self) -> EnumDefinition:
        if len(set(self.labels)) != len(self.labels):
            raise ValueError("duplicate enum labels")
        return self


class EnumColumn(CatalogModel):
    schema_name: str = Field(alias="schema", min_length=1)
    table: str = Field(min_length=1)
    column: str = Field(min_length=1)
    type_schema: str = Field(min_length=1)
    type_name: str = Field(min_length=1)
    mode: Literal["direct", "array", "domain"]


class UnsupportedType(CatalogModel):
    schema_name: str = Field(alias="schema", min_length=1)
    table: str = Field(min_length=1)
    column: str = Field(min_length=1)
    reason: Literal["domain_dependency", "composite_dependency"]


class IncomingForeignKey(CatalogModel):
    schema_name: str = Field(alias="schema", min_length=1)
    table: str = Field(min_length=1)
    name: str = Field(min_length=1)
    target_schema: str = Field(min_length=1)
    target_table: str = Field(min_length=1)
    target_columns: tuple[str, ...] = Field(min_length=1)


class CatalogEvidence(CatalogModel):
    evidence_version: Literal[1]
    scope_schemas: tuple[str, ...]
    relations: tuple[RelationFact, ...]
    constraint_validity: tuple[ConstraintValidity, ...]
    enums: tuple[EnumDefinition, ...]
    enum_columns: tuple[EnumColumn, ...]
    incoming_foreign_keys: tuple[IncomingForeignKey, ...]
    unsupported_types: tuple[UnsupportedType, ...] = ()

    @field_validator("evidence_version", mode="before")
    @classmethod
    def supported_version(cls, value: object) -> object:
        if type(value) is not int or value != 1:
            raise ValueError("catalog evidenceVersion must be integer 1")
        return value

    @model_validator(mode="after")
    def unique_facts(self) -> CatalogEvidence:
        if any(not schema for schema in self.scope_schemas):
            raise ValueError("catalog scope names must be nonempty")
        groups = (
            list(self.scope_schemas),
            [(r.schema_name, r.table) for r in self.relations],
            [(c.schema_name, c.table, c.name) for c in self.constraint_validity],
            [(e.schema_name, e.name) for e in self.enums],
            [(c.schema_name, c.table, c.column) for c in self.enum_columns],
            [(f.schema_name, f.table, f.name) for f in self.incoming_foreign_keys],
            [(c.schema_name, c.table, c.column) for c in self.unsupported_types],
        )
        if any(len(items) != len(set(items)) for items in groups):
            raise ValueError("duplicate catalog evidence")
        return self

    def canonical(self) -> CatalogEvidence:
        return self.model_copy(
            update={
                "scope_schemas": tuple(sorted(self.scope_schemas)),
                "relations": tuple(sorted(self.relations, key=lambda r: (r.schema_name, r.table))),
                "constraint_validity": tuple(
                    sorted(self.constraint_validity, key=lambda c: (c.schema_name, c.table, c.name))
                ),
                "enums": tuple(sorted(self.enums, key=lambda e: (e.schema_name, e.name))),
                "enum_columns": tuple(
                    sorted(self.enum_columns, key=lambda c: (c.schema_name, c.table, c.column))
                ),
                "incoming_foreign_keys": tuple(
                    sorted(
                        self.incoming_foreign_keys, key=lambda f: (f.schema_name, f.table, f.name)
                    )
                ),
                "unsupported_types": tuple(
                    sorted(self.unsupported_types, key=lambda c: (c.schema_name, c.table, c.column))
                ),
            }
        )


def _enum_type_matches(reference: EnumColumn, type_text: str) -> bool:
    """Check the catalog's formatted identifier/array shape; it is not arbitrary SQL."""
    import re

    from sqlglot.errors import TokenError
    from sqlglot.tokenizer_core import TokenType

    from schemasentry.migration import _checked_tokens, fold_identifier

    try:
        tokens = _checked_tokens(type_text)
    except (ValueError, RecursionError, TokenError):
        return False
    array = False
    while len(tokens) >= 2 and (
        tokens[-2].token_type == TokenType.L_BRACKET
        and tokens[-1].token_type == TokenType.R_BRACKET
    ):
        array = True
        tokens = tokens[:-2]
    if array != (reference.mode == "array") or len(tokens) not in (1, 3):
        return False
    if len(tokens) == 3 and tokens[1].token_type != TokenType.DOT:
        return False
    names = []
    for token in tokens[::2]:
        if token.token_type == TokenType.IDENTIFIER:
            names.append(token.text)
        elif re.fullmatch(r"[^\W\d][\w$]*", token.text):
            names.append(fold_identifier(token.text))
        else:
            return False
    return names[-1] == reference.type_name and (
        len(names) == 1 or names[0] == reference.type_schema
    )


def validate_catalog(snapshot: Snapshot) -> None:
    catalog = snapshot.catalog_evidence
    if catalog is None:
        return
    try:
        catalog = CatalogEvidence.model_validate(catalog.model_dump(by_alias=True))
    except ValueError:
        raise ToolError("invalid or duplicate M4 catalog evidence") from None
    tables = {(t.schema_name, t.name): t for t in snapshot.tables}
    if (
        set(catalog.scope_schemas) != set(snapshot.schemas)
        or len(snapshot.schemas) != len(set(snapshot.schemas))
        or any(schema not in catalog.scope_schemas for schema, _ in tables)
    ):
        raise ToolError("catalog evidence scope differs from snapshot scope")
    if {(r.schema_name, r.table) for r in catalog.relations} != set(tables):
        raise ToolError("catalog relation evidence differs from captured tables")
    constraints = {
        (t.schema_name, t.name, c.name): c.kind
        for t in snapshot.tables
        for c in t.constraints
        if c.kind in ("check", "foreign_key")
    }
    if {
        (c.schema_name, c.table, c.name): c.kind for c in catalog.constraint_validity
    } != constraints:
        raise ToolError("catalog constraint evidence differs from captured CHECK/FK constraints")
    enum_keys = {(e.schema_name, e.name) for e in catalog.enums}
    if any(e.schema_name not in catalog.scope_schemas for e in catalog.enums):
        raise ToolError("enum evidence lies outside the declared scope")
    references: tuple[EnumColumn | UnsupportedType, ...] = (
        *catalog.enum_columns,
        *catalog.unsupported_types,
    )
    for ref in references:
        table = tables.get((ref.schema_name, ref.table))
        if table is None or ref.column not in {c.name for c in table.columns}:
            raise ToolError("catalog type reference has no captured column")
    for ref in catalog.enum_columns:
        if (
            ref.type_schema in catalog.scope_schemas
            and (ref.type_schema, ref.type_name) not in enum_keys
        ):
            raise ToolError("catalog enum reference has no scoped enum definition")
        column = next(c for c in tables[ref.schema_name, ref.table].columns if c.name == ref.column)
        if ref.mode == "domain":
            if not any(
                (fact.schema_name, fact.table, fact.column, fact.reason)
                == (ref.schema_name, ref.table, ref.column, "domain_dependency")
                for fact in catalog.unsupported_types
            ):
                raise ToolError("catalog enum domain reference has no explicit dependency gap")
        elif not _enum_type_matches(ref, column.type):
            raise ToolError("catalog enum reference differs from the captured column type")
    incoming = {
        (foreign.schema_name, foreign.table, foreign.name): foreign
        for foreign in catalog.incoming_foreign_keys
    }
    for foreign in catalog.incoming_foreign_keys:
        table = tables.get((foreign.target_schema, foreign.target_table))
        if table is None or not set(foreign.target_columns).issubset(
            {c.name for c in table.columns}
        ):
            raise ToolError("incoming FK evidence has no captured target")
        source = tables.get((foreign.schema_name, foreign.table))
        if source is not None:
            constraint = next((c for c in source.constraints if c.name == foreign.name), None)
            if (
                constraint is None
                or constraint.kind != "foreign_key"
                or constraint.referenced_table != f"{foreign.target_schema}.{foreign.target_table}"
                or tuple(constraint.referenced_columns) != foreign.target_columns
            ):
                raise ToolError("incoming FK evidence differs from the captured source constraint")
    target_names = {f"{schema}.{name}" for schema, name in tables}
    for table in snapshot.tables:
        for constraint in table.constraints:
            if (
                constraint.kind == "foreign_key"
                and constraint.referenced_table in target_names
                and (table.schema_name, table.name, constraint.name) not in incoming
            ):
                raise ToolError("incoming FK evidence omits a captured source constraint")
