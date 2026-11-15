# Changelog

All notable changes to SchemaSentry are documented here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Internal SS001–SS007 classification with immutable deterministic findings, explicit uncertainty
  notices and separate DDL lock/scan/rewrite evidence.
- Bounded SQLGlot PostgreSQL evidence parsing with original statement locations and visible unsupported
  syntax/errors; strict JSON v1 one-to-one column rename hints. Migration input is never executed.
- 59 independently reviewed M3 corpus cases, disposable live PG13/15/16 checks and a repeated Python
  memory workload. [Validation](docs/testing/m3-validation.md) records passing local, branch and PR CI gates.
- [M3 requirements](docs/phases/M3.md), accepted [ADR 0004](docs/adr/0004-m3-classification-evidence.md)
  and a [development-tool audit](docs/DEVELOPMENT-TOOLS.md).

- M2 structural `diff` command, 30 golden snapshot pairs and exact CLI/schema checks.
- Constraint definitions and index key/include evidence, including native ordering flags,
  collation and opclass. Legacy snapshots warn when evidence is missing.
- Versioned diff JSON schema and a hashed runtime dependency lock used by CI and Docker.
- The repository tracks CodeGraph's index ignore rules and documents it as an optional local tool
  for code navigation. Nothing in the build or in CI depends on it.

### Changed

- Canonical Make targets select the Windows/POSIX virtualenv interpreter directly and quote its path;
  lint checks formatting as well as diagnostics. SQLGlot's declaration matches the reviewed 30.31 series.
- Ruff explicitly recognizes the package as first-party, keeping test imports consistent before and
  after new module files exist.
- Snapshot capture now uses a read-only REPEATABLE READ transaction for a consistent catalog view.
- Diff output is UTF-8/LF on Windows pipes. Snapshot input rejects ambiguous JSON fields,
  non-integer versions and duplicate object identities. Feature branches trigger CI.
- The repository is published at https://github.com/Shellghostt/SchemaSentry and the CI workflow has
  executed. The first run on 2026-11-13 passed the PostgreSQL 13, 15 and 16 matrix.

### Planned

- M4: risk scoring, public classification reports, thresholds, `compare`/`explain` and SS008–SS010.

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
