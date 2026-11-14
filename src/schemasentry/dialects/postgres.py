"""PostgreSQL introspection.

All queries read `pg_catalog` / `pg_sequences`. None of them writes, and the
connection is already read-only (see `schemasentry.db`).

Two rules matter for accuracy:

* `reltuples` is -1 when a table has never been analysed on PostgreSQL 14 and
  later, but 0 on PostgreSQL 13, where 0 is ambiguous: it can also mean an
  analysed table that is genuinely empty. The snapshot reports `null` in both
  cases, never `0`, because "unknown" and "empty" are different facts.
* A type the normaliser does not know is kept verbatim in `type` and
  `normalisedType`, with `length` null. Dropping it would hide a column.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from psycopg import Connection

from schemasentry.errors import ToolError
from schemasentry.snapshot import (
    Column,
    Constraint,
    Index,
    Snapshot,
    Table,
)
from schemasentry.snapshot import (
    Sequence as SchemaSequence,
)

SUPPORTED_MAJOR_VERSIONS = range(13, 18)

_NORMALISED_TYPES = {
    "int2": "smallint",
    "int4": "integer",
    "int8": "bigint",
    "float4": "real",
    "float8": "double precision",
    "bool": "boolean",
    "bpchar": "char",
    "varchar": "varchar",
    "timestamptz": "timestamptz",
    "timestamp": "timestamp",
    "timetz": "timetz",
    "time": "time",
    "numeric": "numeric",
    "decimal": "numeric",
    "varbit": "varbit",
    "bit": "bit",
    "bytea": "bytea",
    "json": "json",
    "jsonb": "jsonb",
    "uuid": "uuid",
    "date": "date",
    "interval": "interval",
    "text": "text",
}

_LENGTH_TYPES = frozenset({"varchar", "bpchar", "bit", "varbit"})

_CONSTRAINT_KINDS = {
    "p": "primary_key",
    "u": "unique",
    "f": "foreign_key",
    "c": "check",
    "x": "exclusion",
    "t": "trigger",
}

# attgenerated uses one-letter codes. The snapshot spells them out so a reader
# does not need the PostgreSQL catalog manual to understand the file.
_GENERATION_KINDS = {
    "s": "stored",
}


def _fetch(
    connection: Connection[dict[str, Any]],
    query: str,
    parameters: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(query, parameters)
        return [dict(row) for row in cursor.fetchall()]


def _scalar(connection: Connection[dict[str, Any]], query: str) -> Any:
    with connection.cursor() as cursor:
        cursor.execute(query)
        row = cursor.fetchone()
    if row is None:
        raise ToolError(f"catalog query returned no rows: {query.splitlines()[0]}")
    return next(iter(row.values()))


class PostgresDialect:
    """PostgreSQL 13-17."""

    name = "postgres"

    def capture(
        self,
        connection: Connection[dict[str, Any]],
        *,
        schemas: Sequence[str],
        captured_at: str,
    ) -> Snapshot:
        server_version = str(_scalar(connection, "SHOW server_version"))
        major = _major_version(server_version)
        if major not in SUPPORTED_MAJOR_VERSIONS:
            raise ToolError(
                f"PostgreSQL {major} is not supported; supported majors are "
                f"{SUPPORTED_MAJOR_VERSIONS.start}-{SUPPORTED_MAJOR_VERSIONS.stop - 1}"
            )

        selected = self._select_schemas(connection, schemas)
        tables = self._tables(connection, selected)

        columns: dict[tuple[str, str], list[Column]] = defaultdict(list)
        for row in _fetch(
            connection,
            """
            SELECT n.nspname AS schema,
                   c.relname AS table_name,
                   a.attname AS name,
                   a.attnum AS ordinal,
                   format_type(a.atttypid, a.atttypmod) AS type,
                   t.typname AS type_name,
                   a.atttypmod AS type_modifier,
                   NOT a.attnotnull AS nullable,
                   CASE WHEN a.attgenerated = ''
                        THEN pg_get_expr(d.adbin, d.adrelid) END AS default,
                   a.attidentity AS identity_kind,
                   a.attgenerated AS generated_kind,
                   CASE WHEN a.attgenerated <> ''
                        THEN pg_get_expr(d.adbin, d.adrelid) END AS generation_expression
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_type t ON t.oid = a.atttypid
            LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE a.attnum > 0
              AND NOT a.attisdropped
              AND c.relkind IN ('r', 'p')
              AND n.nspname = ANY(%s)
            ORDER BY n.nspname, c.relname, a.attnum
            """,
            (list(selected),),
        ):
            type_name = str(row["type_name"])
            columns[(row["schema"], row["table_name"])].append(
                Column(
                    name=str(row["name"]),
                    ordinal=int(row["ordinal"]),
                    type=str(row["type"]),
                    normalised_type=_NORMALISED_TYPES.get(type_name, type_name),
                    length=_length(type_name, int(row["type_modifier"])),
                    nullable=bool(row["nullable"]),
                    default=row["default"],
                    identity=bool(row["identity_kind"]),
                    generated=_GENERATION_KINDS.get(str(row["generated_kind"])),
                    generation_expression=row["generation_expression"],
                )
            )

        constraints: dict[tuple[str, str], list[Constraint]] = defaultdict(list)
        for row in _fetch(
            connection,
            """
            SELECT n.nspname AS schema,
                   c.relname AS table_name,
                   con.conname AS name,
                   con.contype AS kind,
                   pg_get_constraintdef(con.oid, true) AS definition,
                   rn.nspname || '.' || rc.relname AS referenced_table,
                   COALESCE((
                       SELECT array_agg(a.attname ORDER BY k.ord)
                       FROM unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
                       JOIN pg_attribute a
                         ON a.attrelid = con.conrelid AND a.attnum = k.attnum
                   ), ARRAY[]::text[]) AS columns,
                   COALESCE((
                       SELECT array_agg(a.attname ORDER BY k.ord)
                       FROM unnest(con.confkey) WITH ORDINALITY AS k(attnum, ord)
                       JOIN pg_attribute a
                         ON a.attrelid = con.confrelid AND a.attnum = k.attnum
                   ), ARRAY[]::text[]) AS referenced_columns
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_class rc ON rc.oid = con.confrelid
            LEFT JOIN pg_namespace rn ON rn.oid = rc.relnamespace
            WHERE con.contype IN ('p', 'u', 'f', 'c', 'x', 't')
              AND n.nspname = ANY(%s)
            ORDER BY n.nspname, c.relname, con.contype, con.conname
            """,
            (list(selected),),
        ):
            kind = _CONSTRAINT_KINDS[str(row["kind"])]
            constraints[(row["schema"], row["table_name"])].append(
                Constraint(
                    name=str(row["name"]),
                    kind=kind,
                    definition=str(row["definition"]),
                    columns=[str(column) for column in row["columns"]],
                    referenced_table=row["referenced_table"] if kind == "foreign_key" else None,
                    referenced_columns=(
                        [str(column) for column in row["referenced_columns"]]
                        if kind == "foreign_key"
                        else []
                    ),
                )
            )

        indexes: dict[tuple[str, str], list[Index]] = defaultdict(list)
        for row in _fetch(
            connection,
            """
            SELECT n.nspname AS schema,
                   c.relname AS table_name,
                   ic.relname AS name,
                   ix.indisunique AS is_unique,
                   am.amname AS method,
                   pg_get_expr(ix.indpred, ix.indrelid) AS predicate,
                   pg_get_expr(ix.indexprs, ix.indrelid) AS expression,
                   ix.indisvalid AS valid,
                   ARRAY(
                       SELECT pg_get_indexdef(ix.indexrelid, k, true)
                           || CASE WHEN (ix.indoption[k-1] & 1) = 1 THEN ' DESC' ELSE ' ASC' END
                           || CASE WHEN (ix.indoption[k-1] & 2) = 2
                                   THEN ' NULLS FIRST' ELSE ' NULLS LAST' END
                           || COALESCE(' COLLATE ' || quote_ident(cn.nspname)
                                       || '.' || quote_ident(co.collname), '')
                           || ' OPCLASS ' || quote_ident(onsp.nspname)
                               || '.' || quote_ident(op.opcname)
                       FROM generate_series(1, ix.indnkeyatts) k
                       JOIN pg_opclass op ON op.oid = ix.indclass[k-1]
                       JOIN pg_namespace onsp ON onsp.oid = op.opcnamespace
                       LEFT JOIN pg_collation co ON co.oid = ix.indcollation[k-1]
                       LEFT JOIN pg_namespace cn ON cn.oid = co.collnamespace
                       ORDER BY k
                   ) AS keys,
                   ARRAY(SELECT a.attname FROM unnest(ix.indkey) WITH ORDINALITY k(attnum, ord)
                         JOIN pg_attribute a ON a.attrelid=ix.indrelid AND a.attnum=k.attnum
                         WHERE k.ord > ix.indnkeyatts ORDER BY k.ord) AS included_columns,
                   COALESCE((
                       SELECT array_agg(a.attname ORDER BY k.ord)
                       FROM unnest(ix.indkey) WITH ORDINALITY AS k(attnum, ord)
                       JOIN pg_attribute a
                         ON a.attrelid = ix.indrelid AND a.attnum = k.attnum
                       WHERE k.attnum > 0
                   ), ARRAY[]::text[]) AS columns
            FROM pg_index ix
            JOIN pg_class c ON c.oid = ix.indrelid
            JOIN pg_class ic ON ic.oid = ix.indexrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_am am ON am.oid = ic.relam
            WHERE n.nspname = ANY(%s)
            ORDER BY n.nspname, c.relname, ic.relname
            """,
            (list(selected),),
        ):
            indexes[(row["schema"], row["table_name"])].append(
                Index(
                    name=str(row["name"]),
                    columns=[str(column) for column in row["columns"]],
                    unique=bool(row["is_unique"]),
                    method=str(row["method"]),
                    predicate=row["predicate"],
                    valid=bool(row["valid"]),
                    expression=row["expression"],
                    keys=[str(key) for key in row["keys"]],
                    included_columns=[str(column) for column in row["included_columns"]],
                )
            )

        built: list[Table] = []
        for row in tables:
            key = (row["schema"], row["name"])
            estimate = row["row_estimate"]
            built.append(
                Table(
                    schema=row["schema"],
                    name=row["name"],
                    row_estimate=None if estimate is None else int(float(estimate)),
                    total_bytes=int(row["total_bytes"]),
                    columns=columns[key],
                    constraints=constraints[key],
                    indexes=indexes[key],
                )
            )

        sequences = [
            SchemaSequence(
                schema=row["schema"],
                name=str(row["name"]),
                data_type=str(row["data_type"]),
                start_value=int(row["start_value"]),
                increment_by=int(row["increment_by"]),
                cycle=bool(row["cycle"]),
            )
            for row in _fetch(
                connection,
                """
                SELECT schemaname AS schema,
                       sequencename AS name,
                       data_type::text AS data_type,
                       start_value,
                       increment_by,
                       cycle
                FROM pg_sequences
                WHERE schemaname = ANY(%s)
                ORDER BY schemaname, sequencename
                """,
                (list(selected),),
            )
        ]

        extensions = [
            str(row["name"])
            for row in _fetch(
                connection, "SELECT extname AS name FROM pg_extension ORDER BY extname"
            )
        ]

        return Snapshot(
            dialect=self.name,
            server_version=server_version,
            captured_at=captured_at,
            database=str(_scalar(connection, "SELECT current_database()")),
            schemas=selected,
            tables=built,
            sequences=sequences,
            extensions=extensions,
        )

    def _select_schemas(
        self, connection: Connection[dict[str, Any]], requested: Sequence[str]
    ) -> list[str]:
        if requested:
            rows = _fetch(
                connection,
                "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s) ORDER BY nspname",
                (list(dict.fromkeys(requested)),),
            )
            existing = [str(row["nspname"]) for row in rows]
            missing = sorted(set(requested) - set(existing))
            if missing:
                raise ToolError(f"schema not found: {', '.join(missing)}")
            return existing

        rows = _fetch(
            connection,
            """
            SELECT nspname
            FROM pg_namespace
            WHERE nspname !~ '^pg_'
              AND nspname <> 'information_schema'
            ORDER BY nspname
            """,
        )
        return [str(row["nspname"]) for row in rows]

    @staticmethod
    def _tables(
        connection: Connection[dict[str, Any]], schemas: Sequence[str]
    ) -> list[dict[str, Any]]:
        return _fetch(
            connection,
            """
            SELECT n.nspname AS schema,
                   c.relname AS name,
                   CASE
                       WHEN c.reltuples < 0 THEN NULL
                       WHEN c.reltuples = 0
                            AND COALESCE(
                                st.last_analyze,
                                st.last_autoanalyze,
                                st.last_vacuum,
                                st.last_autovacuum
                            ) IS NULL
                           THEN NULL
                       ELSE c.reltuples::double precision
                   END AS row_estimate,
                   pg_total_relation_size(c.oid) AS total_bytes
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            LEFT JOIN pg_stat_user_tables st ON st.relid = c.oid
            WHERE c.relkind IN ('r', 'p')
              AND n.nspname = ANY(%s)
            ORDER BY n.nspname, c.relname
            """,
            (list(schemas),),
        )


def _major_version(server_version: str) -> int:
    match = re.match(r"^(\d+)", server_version)
    if match is None:
        raise ToolError(f"could not parse the server version {server_version!r}")
    return int(match.group(1))


def _length(type_name: str, type_modifier: int) -> int | None:
    if type_name in _LENGTH_TYPES and type_modifier > 4:
        return type_modifier - 4
    return None
