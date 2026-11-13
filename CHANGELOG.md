# Changelog

All notable changes to SchemaSentry are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- The repository is published at https://github.com/Shellghostt/SchemaSentry and the CI workflow has
  executed. The first run on 2026-11-13 passed the PostgreSQL 13, 15 and 16 matrix.

### Planned

- M2: comparison engine over two snapshot files, with fixture pairs and golden diff tests.

## [0.1.0] - 2026-11-13

### Added

- `schemasentry snapshot` with `--database`, `--output`, `--schema` and `--captured-at`.
  `--database` falls back to `SCHEMASENTRY_DATABASE_URL`.
- `schemasentry version`.
- Read-only connection with `statement_timeout = 5s`. The integration test proves the server
  refuses a write on that connection.
- PostgreSQL introspection for server majors 13 to 17: tables, columns, types, nullability,
  defaults, identity, generated columns, constraints (including foreign key targets), indexes
  (including partial and expression indexes), sequences and extensions.
- Snapshot model with deterministic ordering and a byte-stable serialiser. `--captured-at` and
  `SOURCE_DATE_EPOCH` make the timestamp reproducible.
- Committed JSON Schema in `docs/schema/snapshot-v1.schema.json`, validated against a real captured
  snapshot by the test suite.
- Integration suite that runs against a real PostgreSQL server; it was run locally against
  PostgreSQL 13.23, 15 and 16.16.
- CI workflow with an integration job that runs the suite against PostgreSQL 13, 15 and 16.
- ADR 0002, recording the M1 decisions, including the PostgreSQL 13 versus 14 difference in how an
  unanalysed table reports its row estimate.

### Known limitations

- Nothing is compared yet. There is no diff engine, no rule, no risk score, no report and no corpus
  case, so the tool cannot yet say whether a migration is dangerous.
- Exit codes 1 and 2 are unreachable in this release.
- The CI workflow had not executed when this tag was created: the repository had no remote yet. It has
  since run on GitHub; see [Unreleased].
- PostgreSQL 14 and 17 are within the supported range and use the same code paths as 13, 15 and 16,
  but only 13, 15 and 16 are in the CI matrix.
- `sqlglot` and `pyyaml` are declared dependencies but are not used by any code path yet; they are
  locked decisions for M5 and M3.

## [0.0.0] - 2026-11-13

- Initial skeleton. No functionality.
