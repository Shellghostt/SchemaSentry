# ADR 0003 — Structural comparison and snapshot evidence

- Status: accepted on the M2 feature branch
- Date: 2026-11-14

M2 compares version-1 PostgreSQL snapshot files without a database connection. It reports table,
column, constraint and index changes. Successful comparison exits 0 even with changes; migration
parsing, risk thresholds, classification and scoring remain later milestones.

Objects use schema/table/name identity. Column ordinals, capture metadata and table statistics are
excluded from equality. Constraint/index contents match before names so renames, including backing
index renames, do not become false drop/add changes. Unknown types and modifiers remain verbatim.
Sequences, extensions, schema membership and uncaptured table properties are not compared.

Version 1 gains optional constraint `definition` and index `keys`/`includedColumns`. Catalog keys
include direction, null ordering, collation and opclass; the column form of `pg_get_indexdef` alone
omits ordering flags. Legacy snapshots warn when evidence is absent. Recapture both inputs with the
same collector; SQL-expression equivalence across server versions is not inferred.

Capture uses a read-only REPEATABLE READ transaction and the existing five-second statement timeout.
Offline input is capped at 64 MiB and rejects unknown fields, duplicate JSON fields/object identities,
unsupported dialects and non-integer versions. Diff JSON is UTF-8/LF, sorted by schema/table/object/kind,
with a committed schema. It contains no DSN. Thirty fixture pairs and real CLI subprocesses establish
the structural contract; live PG 13/15/16 tests cover renames and definition changes.

Runtime dependencies are pinned with hashes in `requirements.lock`, used by CI, the runtime image
and the audit. Feature branches trigger CI. No release or merge into main is part of M2 completion.
