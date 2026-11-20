"""Read-only, scoped, row-bounded M4 catalog evidence in the capture transaction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, LiteralString

import psycopg
from psycopg.rows import dict_row

from schemasentry.catalog_models import (
    CatalogEvidence,
    ConstraintValidity,
    EnumColumn,
    EnumDefinition,
    IncomingForeignKey,
    RelationFact,
    UnsupportedType,
    validate_catalog,
)
from schemasentry.errors import ToolError
from schemasentry.snapshot import Snapshot

MAX_CATALOG_ROWS = 200_000


@dataclass
class _CatalogBudget:
    remaining: int = MAX_CATALOG_ROWS


def _rows(
    connection: psycopg.Connection[Any],
    query: LiteralString,
    scopes: list[str],
    budget: _CatalogBudget,
) -> list[dict[str, Any]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(query, (scopes, budget.remaining + 1))
        rows = cursor.fetchall()
    if len(rows) > budget.remaining:
        raise ToolError("M4 catalog evidence exceeds its row bound")
    budget.remaining -= len(rows)
    return rows


def capture_catalog(connection: psycopg.Connection[Any], snapshot: Snapshot) -> CatalogEvidence:
    scopes = snapshot.schemas
    budget = _CatalogBudget()
    relations = tuple(
        RelationFact(
            schema=row["schema"],
            table=row["table_name"],
            kind="partitioned" if row["kind"] == "p" else "ordinary",
        )
        for row in _rows(
            connection,
            """
            SELECT n.nspname AS schema, c.relname AS table_name, c.relkind AS kind
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE c.relkind IN ('r','p') AND n.nspname=ANY(%s)
            ORDER BY n.nspname,c.relname LIMIT %s
            """,
            scopes,
            budget,
        )
    )
    constraints = tuple(
        ConstraintValidity(
            schema=row["schema"],
            table=row["table_name"],
            name=row["name"],
            kind="check" if row["kind"] == "c" else "foreign_key",
            validated=row["validated"],
        )
        for row in _rows(
            connection,
            """
            SELECT n.nspname AS schema,c.relname AS table_name,con.conname AS name,
                   con.contype AS kind,con.convalidated AS validated
            FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE con.contype IN ('c','f') AND c.relkind IN ('r','p') AND n.nspname=ANY(%s)
            ORDER BY n.nspname,c.relname,con.conname LIMIT %s
            """,
            scopes,
            budget,
        )
    )
    labels: dict[tuple[str, str], list[str]] = {}
    for row in _rows(
        connection,
        """
        SELECT n.nspname AS schema,t.typname AS name,e.enumlabel AS label
        FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
        LEFT JOIN pg_enum e ON e.enumtypid=t.oid
        WHERE t.typtype='e' AND n.nspname=ANY(%s)
        ORDER BY n.nspname,t.typname,e.enumsortorder LIMIT %s
        """,
        scopes,
        budget,
    ):
        values = labels.setdefault((row["schema"], row["name"]), [])
        if row["label"] is not None:
            values.append(row["label"])
    # A nonempty enum needs a definition object in addition to its label rows.
    budget.remaining -= sum(bool(values) for values in labels.values())
    if budget.remaining < 0:
        raise ToolError("M4 catalog evidence exceeds its object bound")
    enums = tuple(
        EnumDefinition(schema=schema, name=name, labels=tuple(values))
        for (schema, name), values in labels.items()
    )
    references = tuple(
        EnumColumn(
            schema=row["schema"],
            table=row["table_name"],
            column=row["column_name"],
            type_schema=row["type_schema"],
            type_name=row["type_name"],
            mode=row["mode"],
        )
        for row in _rows(
            connection,
            """
            SELECT n.nspname AS schema,c.relname AS table_name,a.attname AS column_name,
                   en.nspname AS type_schema,et.typname AS type_name,
                   CASE WHEN ct.typtype='e' THEN 'direct'
                        WHEN ct.typtype='d' THEN 'domain' ELSE 'array' END AS mode
            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_type ct ON ct.oid=a.atttypid
            JOIN pg_type et ON et.oid=CASE
                WHEN ct.typtype='e' THEN ct.oid
                WHEN ct.typtype='d' THEN ct.typbasetype ELSE ct.typelem END
            JOIN pg_namespace en ON en.oid=et.typnamespace
            WHERE a.attnum>0 AND NOT a.attisdropped AND c.relkind IN ('r','p')
              AND et.typtype='e' AND n.nspname=ANY(%s)
            ORDER BY n.nspname,c.relname,a.attnum LIMIT %s
            """,
            scopes,
            budget,
        )
    )
    unsupported = tuple(
        UnsupportedType(
            schema=row["schema"],
            table=row["table_name"],
            column=row["column_name"],
            reason="domain_dependency" if row["kind"] == "d" else "composite_dependency",
        )
        for row in _rows(
            connection,
            """
            SELECT n.nspname AS schema,c.relname AS table_name,a.attname AS column_name,
                   CASE WHEN t.typtype IN ('d','c') THEN t.typtype ELSE et.typtype END AS kind
            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace JOIN pg_type t ON t.oid=a.atttypid
            LEFT JOIN pg_type et ON et.oid=t.typelem
            WHERE a.attnum>0 AND NOT a.attisdropped AND c.relkind IN ('r','p')
              AND (t.typtype IN ('d','c') OR et.typtype IN ('d','c')) AND n.nspname=ANY(%s)
            ORDER BY n.nspname,c.relname,a.attnum LIMIT %s
            """,
            scopes,
            budget,
        )
    )
    incoming = tuple(
        IncomingForeignKey(
            schema=row["schema"],
            table=row["table_name"],
            name=row["name"],
            target_schema=row["target_schema"],
            target_table=row["target_table"],
            target_columns=tuple(row["target_columns"]),
        )
        for row in _rows(
            connection,
            """
            SELECT sn.nspname AS schema,sc.relname AS table_name,con.conname AS name,
                   tn.nspname AS target_schema,tc.relname AS target_table,
                   ARRAY(SELECT a.attname FROM unnest(con.confkey) WITH ORDINALITY k(num,ord)
                         JOIN pg_attribute a ON a.attrelid=con.confrelid AND a.attnum=k.num
                         ORDER BY k.ord) AS target_columns
            FROM pg_constraint con JOIN pg_class sc ON sc.oid=con.conrelid
            JOIN pg_namespace sn ON sn.oid=sc.relnamespace
            JOIN pg_class tc ON tc.oid=con.confrelid
            JOIN pg_namespace tn ON tn.oid=tc.relnamespace
            WHERE con.contype='f' AND tn.nspname=ANY(%s)
            ORDER BY sn.nspname,sc.relname,con.conname LIMIT %s
            """,
            scopes,
            budget,
        )
    )
    count = sum(map(len, (relations, constraints, references, unsupported, incoming, enums)))
    count += sum(len(enum.labels) for enum in enums)
    if count > MAX_CATALOG_ROWS:
        raise ToolError("M4 catalog evidence exceeds its object bound")
    catalog = CatalogEvidence(
        evidence_version=1,
        scope_schemas=tuple(scopes),
        relations=relations,
        constraint_validity=constraints,
        enums=enums,
        enum_columns=references,
        incoming_foreign_keys=incoming,
        unsupported_types=unsupported,
    ).canonical()
    validate_catalog(snapshot.model_copy(update={"catalog_evidence": catalog}))
    return catalog
