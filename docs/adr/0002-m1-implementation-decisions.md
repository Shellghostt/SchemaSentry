# ADR 0002 - M1 implementation decisions

- Status: accepted
- Date: 2026-11-13
- Deciders: Aditya

## Context

M1 delivers the first usable thing SchemaSentry can do: capture the schema of a live PostgreSQL
database as a deterministic JSON snapshot. The decisions below were made while building it, are
expensive to change later, and are not fully determined by PLAN section 7.

## Decisions

1. **The snapshot format is defined by a committed JSON Schema, not only by the plan.**
   `docs/schema/snapshot-v1.schema.json` is the machine-readable contract, and a test validates a
   real captured snapshot against it. The plan's example in section 7 stays readable, but the schema
   is what code and CI agree on.
2. **Three fields are added to the section 7 example.** `generationExpression` on a column (the
   server's rendering of a generated column's expression), `referencedTable` and
   `referencedColumns` on a foreign key, and `expression` on an index. Each one exists because
   without it the snapshot would state something false: a generated column's expression is not a
   default, a foreign key without its target is half a constraint, and an index on `lower(email)`
   is not an index on `email`.
3. **`capturedAt` is reproducible.** `--captured-at` takes an ISO 8601 timestamp and
   `SOURCE_DATE_EPOCH` is honoured, so two runs over an unchanged database can produce
   byte-identical files. Without this the acceptance criterion "two runs produce byte-identical
   output" would be impossible to meet for any file containing a timestamp.
4. **Write protection is the transaction, not a promise.** Every catalog read happens inside a
   read-only transaction with `statement_timeout = 5s`. The integration test asserts that a
   `CREATE TABLE` on that connection is refused by PostgreSQL itself.
5. **A row estimate is `null` when it is unknown, never `0`.** PostgreSQL 14 and later store -1 in
   `pg_class.reltuples` for a table that has never been analysed. PostgreSQL 13 stores `0`, which is
   ambiguous: it also means an analysed table that is genuinely empty. The snapshot therefore also
   consults `pg_stat_user_tables`, and reports `null` unless the table has been analysed at least
   once. On PostgreSQL 13 the statistics collector publishes that information a fraction of a second
   after `ANALYZE`, so a snapshot taken in that window reports `null`, which is the conservative
   answer. The estimate itself is the server's estimate and may be stale.
6. **Unknown types are preserved verbatim.** `type` is `format_type` output, exactly as PostgreSQL
   renders it, and `normalisedType` falls back to the type's own name for anything the normaliser
   does not know. A column with a user-defined type is never dropped and never guessed.
7. **Supported server majors are 13 to 17, and anything else is refused.** The tool says
   "PostgreSQL 18 is not supported" instead of trying and reporting version-specific behaviour it
   has not tested. The CI matrix covers 13, 15 and 16; 14 and 17 are covered by the same code paths
   as their neighbours but are not in the matrix, so the README says so plainly.
8. **A sequence's current value is not captured.** It changes on every `nextval`, which would break
   determinism. The definition (type, start, increment, cycle) is stable and is captured.
9. **Usage errors exit with code 4.** The command framework uses code 2 for a usage error; the CLI
   translates it to the code documented in PLAN section 8, because exit codes are public API.
   Running the tool with no command prints the help text and exits 4.
10. **The dialect layer is a real interface, even with one implementation.** The catalog queries
    live in `schemasentry/dialects/postgres.py`; the CLI and the serialiser never see SQL. MySQL is
    additive work, not a fork.
11. **`sqlglot` and `pyyaml` stay declared but unused.** They are locked decisions for M5 (migration
    parsing) and M3 (hints). They are not used by any code path in M1, and nothing in this release
    claims otherwise.

## Consequences

- `schemasentry snapshot` works against a real PostgreSQL 13, 15 and 16 server; the integration
  suite passes against all three.
- A snapshot is reviewable in a pull request: stable ordering, stable formatting, no timestamps
  that move on their own.
- The tool cannot write to the database, and the test suite proves it against the server rather
  than against the source code.
- Nothing here analyses a migration. There are no rules, no risk scores and no reports yet.
