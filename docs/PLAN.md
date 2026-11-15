---
project: SchemaSentry
slug: schemasentry
owner: shellghostt
status: mvp
version: 0.1.0
language: Python 3.12
license: Apache-2.0
rank: 3
focus: Database engineering
depends_on:
  - PostgreSQL 13+ (first supported dialect)
  - Python 3.12+
created: 2026-11-13
updated: 2026-11-15
---

# SchemaSentry — Implementation Plan

> **This file is the specification.** Accuracy claims are defined by `tests/corpus/`, not by opinion.

---

## 0. Machine context

M2 is complete and merged into `main`; M3 is **complete, including branch and PR CI**, on
`feat/m3-implementation`. [ADR 0004](adr/0004-m3-classification-evidence.md) defines the internal
evidence API. The [M3 requirements](phases/M3.md) and [validation record](testing/m3-validation.md)
record 59 reviewed cases, live PG13/15/16 evidence and canonical local gates.
The [development-tool audit](DEVELOPMENT-TOOLS.md) records profiling limits. No M3 release or merge
is claimed; public reports and risk scoring remain M4.

```yaml
project: SchemaSentry
status: mvp
version: 0.1.0
builds: true
functional: partial            # M1/M2 and internal M3 work; public risk/report flow remains M4

implemented:
  - typer cli with version, snapshot and structural diff
  - snapshot --database, --output, --schema, --captured-at
  - read-only connection with statement_timeout = 5s
  - postgres dialect (pg_catalog introspection) for server majors 13 to 17
  - snapshot model with deterministic ordering and serialisation
  - committed json schema (docs/schema/snapshot-v1.schema.json) enforced by tests
  - integration suite that runs against a real postgres server
  - offline structural comparison, deterministic UTF-8/LF JSON and 30 exact fixture pairs
  - bounded/validated snapshot loading and warnings for legacy evidence
  - read-only REPEATABLE READ capture and full index ordering/collation/opclass metadata
  - hashed runtime dependencies and feature-branch CI
  - exit codes 0, 3 and 4 (1 and 2 belong to the risk milestones)
  - internal deterministic classification registry SS001-SS007 with evidence and limitations
  - bounded SQLGlot PostgreSQL evidence parser with visible unsupported/errors and no SQL execution
  - strict JSON v1 one-to-one column rename hints inside classification
  - 59 reviewed corpus cases and disposable live PG13/15/16 classification evidence
  - native Python lifecycle profiling and installed Docker runtime checks

not_implemented:
  - risk scoring
  - public markdown and json classification reports
  - compare, explain and rules commands
  - migration-to-snapshot prediction and broader parser integration
  - ownership hints and hint format v2
  - github action
  - mysql support

source_of_truth:
  scope_and_rules: docs/PLAN.md        # this file, section 9
  accuracy_contract: tests/corpus/     # a rule change that breaks a case is wrong
  architecture: docs/ARCHITECTURE.md
  decisions: docs/adr/
  status: README.md#roadmap
  snapshot_contract: docs/schema/snapshot-v1.schema.json

forbidden_claims:
  - "detects all dangerous migrations"
  - "safe" or "guaranteed" about any migration
  - support for a database version not in the support matrix
  - a rule that has no corpus case

if_uncertain:
  - add a corpus case before changing a rule
  - if lock behaviour is version-dependent, cite the PostgreSQL version in the rule
  - never estimate a duration without row counts; say "unknown" instead
```

---

## 1. What this is

A CLI and CI gate that compares the schema you have with the schema a migration will produce, classifies
each difference, and scores the risk before the migration touches production.

One-line description: *Detect dangerous database schema changes before they reach production.*

---

## 2. Problem and users

**Problem.** Migration review is done by eye, by people who are not database specialists, under time
pressure. `ALTER TABLE users ALTER COLUMN email TYPE varchar(320)` looks harmless. `ALTER TABLE orders ADD
COLUMN status text NOT NULL DEFAULT 'new'` takes an ACCESS EXCLUSIVE lock and — on older versions — rewrites
the table. Both pass review and fail in production at 09:00.

**Users.**

| User | Need |
|---|---|
| Backend developer | Know before merging whether a migration is dangerous |
| DBA / platform engineer | A policy gate that fails the build, with reasons |
| Reviewer | A short report that explains risk, not a wall of SQL |

**Success looks like.** A pull request that drops a column fails CI with a report naming the table, the
column and the safest alternative pattern.

---

## 3. Non-goals

- **Not a migration runner.** It does not apply migrations. Flyway, Alembic, Atlas and friends already exist.
- **Not a schema linter for style.** Naming conventions are somebody else's tool.
- **Not an ORM.** It reads the database, not your models.
- **Not a performance profiler.** It estimates lock *risk*, never query speed.
- **No hosted service.** CI and CLI only.
- **No "AI review" of migrations.** Rule-based, deterministic, reviewable.

---

## 4. Scope contract

### v0.1 — MVP (M1–M4)

PostgreSQL only. Snapshot, compare two snapshots, classify seven rules, score risk, Markdown and JSON
report, documented exit codes.

### v1.0 (M5–M6)

GitHub Action, baseline storage convention, MySQL dialect behind the same interface, performance analysis
on a real dataset, 100+ corpus cases.

### Post-1.0

SQLite, SQL Server, migration hints file format v2, historical drift detection, policy files.

---

## 5. Locked decisions

| # | Decision | Rationale |
|---|---|---|
| 1 | Python + Typer | `sqlglot` and the introspection ecosystem are Python-first; CI use needs no static binary |
| 2 | Compare normalised schema **state**, not SQL text | Text diffs are wrong in both directions |
| 3 | SQL parsing is a secondary signal | Used for lock and rewrite analysis, never for breakage decisions alone |
| 4 | PostgreSQL first, MySQL later | One dialect done properly; the dialect layer exists from M1 |
| 5 | Golden corpus defines accuracy | Rules are falsifiable by committed cases |
| 6 | Exit codes are public API | CI depends on them; changing them is a breaking change |
| 7 | Read-only database access | The tool never issues DDL or DML |
| 8 | Reports are deterministic | Same inputs produce byte-identical JSON, so diffs are reviewable |

**Rejected alternatives:** comparing `pg_dump` text output (formatting noise, unstable ordering), running the
migration on a copy and diffing (requires production-like data and time), an LLM reviewer (non-deterministic,
unauditable), Go (weaker SQL parsing ecosystem at the time of writing).

---

## 6. Architecture

```mermaid
flowchart LR
    DB[(Database)] --> INTRO[Schema introspection]
    MIG[Migration files] --> PARSE[Migration parser]
    INTRO --> NORM[Normalised snapshot]
    PARSE --> NORM2[Predicted snapshot]
    NORM --> CMP[Schema comparator]
    NORM2 --> CMP
    CMP --> CLASS[Change classification]
    CLASS --> RISK[Risk scoring]
    RISK --> REP[Markdown / JSON report]
    REP --> CI[CI exit code]
```

**Two modes, one engine:**

1. **Diff mode** — compare two snapshot files (`--before`, `--after`). No database needed.
2. **Predict mode** — snapshot the live database, parse migration files, apply the *schema delta* to the
   snapshot in memory, compare. No migration is executed. Ever.

Mode 2 is best-effort by design: SQL that cannot be modelled statically is reported as
`unanalysable_statement` with the raw text, and the run exits `1` unless `--allow-unanalysable` is set.

---

## 7. Data model

**Snapshot** (`schemaVersion: 1`), JSON, sorted deterministically:

```json
{
  "schemaVersion": 1,
  "dialect": "postgres",
  "serverVersion": "16.4",
  "capturedAt": "2026-11-13T10:00:00Z",
  "database": "app",
  "schemas": ["public"],
  "tables": [
    {
      "schema": "public",
      "name": "users",
      "rowEstimate": 1820000,
      "totalBytes": 734003200,
      "columns": [
        {
          "name": "email",
          "ordinal": 3,
          "type": "character varying(255)",
          "normalisedType": "varchar",
          "length": 255,
          "nullable": false,
          "default": null,
          "identity": false,
          "generated": null
        }
      ],
      "constraints": [
        { "name": "users_pkey", "kind": "primary_key", "columns": ["id"] },
        { "name": "users_email_key", "kind": "unique", "columns": ["email"] }
      ],
      "indexes": [
        {
          "name": "users_email_idx",
          "columns": ["email"],
          "unique": false,
          "method": "btree",
          "predicate": null,
          "valid": true
        }
      ]
    }
  ],
  "sequences": [],
  "extensions": ["pgcrypto"]
}
```

Row estimates come from `pg_class.reltuples`; when the table has never been analysed, `rowEstimate` is `null`
and every size-dependent rule reports `confidence: low` instead of guessing.

The machine-readable contract is `docs/schema/snapshot-v1.schema.json`, and a test validates a real
captured snapshot against it. It adds three fields to the example above, each because the shorter form
would state something false: `generationExpression` on a generated column, `referencedTable` and
`referencedColumns` on a foreign key, and `expression` on an index. See ADR 0002.

**Finding** (`expected.json` in the corpus):

```json
{
  "changes": [
    {
      "ruleId": "SS001",
      "severity": "critical",
      "object": "users.email",
      "change": "column_removed",
      "details": { "type": "varchar(255)", "nullable": false }
    }
  ],
  "risk": "critical",
  "exitCode": 2,
  "lock": { "level": "access_exclusive", "rewritesTable": false, "estimatedSeconds": null }
}
```

---

## 8. Command surface and exit codes

```
schemasentry snapshot  --database URL --output snap.json
schemasentry compare   --baseline snap.json --database URL [--migrations ./migrations]
                       --format markdown|json --fail-on low|medium|high|critical
schemasentry diff      --before a.json --after b.json [--format ...]
schemasentry explain   <rule-id>
schemasentry rules     [--json]
schemasentry version
```

| Exit code | Meaning |
|---|---|
| 0 | No finding at or above `--fail-on` (default `high`) |
| 1 | Threshold crossed (report printed) |
| 2 | Blocking risk found (`critical`) |
| 3 | Tool error: connection, parse failure, unsupported dialect |
| 4 | Invalid usage |

`--database` is read from the environment by default (`SCHEMASENTRY_DATABASE_URL`), never from a flag in CI
logs. The tool opens a read-only transaction and sets `statement_timeout = 5s`.

Implemented in M2: `snapshot`, `diff --before FILE --after FILE` and `version`. Diff prints structural
JSON and exits 0 even with changes. M3 classification is an internal library API; thresholds and
public reports remain M4, and codes 1 and 2 are unreachable through M3. Input is capped at 64 MiB;
malformed/ambiguous input exits 3. See [M3 validation](testing/m3-validation.md) for the evidence API.

---

## 9. Rules

Stable ids. One page each in `docs/rules/`. Every rule has at least one corpus case.

| ID | Detects | Base severity | Notes |
|---|---|---|---|
| SS001 | Column removed | critical | Breaks readers still referencing that column |
| SS002 | Column type changed | high | Some changes are safe; see table below |
| SS003 | NOT NULL added without validated evidence that existing rows satisfy it | high | Defaults are not proof; validated CHECK evidence can avoid a scan on supported versions |
| SS004 | Missing index on a foreign key | medium | Scaled by table size; write-path amplification |
| SS005 | Locking or rewriting statement | high | `ALTER TYPE`, `SET NOT NULL`, `ADD COLUMN ... DEFAULT`, `VACUUM FULL` |
| SS006 | Rename appearing as drop + add | high | Requires a rename hint file, otherwise data loss risk |
| SS007 | Known volatile default or unknown function volatility | medium | Nonliteral does not imply volatile; PG11+ non-volatile ADD COLUMN defaults can avoid rewrite |
| SS008 | Constraint added without `NOT VALID` | medium | M4; supported CHECK/FK constraints can be validated separately |
| SS009 | Index created without `CONCURRENTLY` | medium | M4; blocks writes for the duration of the build |
| SS010 | Enum value removed or renamed | high | M4; PostgreSQL has no direct enum-value removal operation |

**Type-change nuance for SS002** (the rule must not cry wolf):

| Change | Verdict |
|---|---|
| `varchar(50)` → `varchar(100)` | safe, no rewrite |
| `varchar(100)` → `varchar(50)` | high, data truncation |
| `int` → `bigint` | medium, table rewrite |
| `bigint` → `int` | high, overflow risk |
| `text` → `varchar(n)` | high, needs validation query |
| `timestamp` → `timestamptz` | high, silent timezone reinterpretation |
| `numeric(p,s)` widening | medium; conversion/scan/rewrite depends on typmod and server evidence |

Base severities are policy; cast/lock/rewrite claims require version-specific evidence. USING expressions,
unknown types and user-function volatility must not be treated as safe by inference. See [M3 requirements](phases/M3.md).

**Risk scoring.** `risk = max(base severity, size modifier, lock modifier)`, then one level up if the object is
referenced by a foreign key or a unique constraint.

| Modifier | Condition |
|---|---|
| +1 level | table is referenced by 2+ foreign keys |
| +1 level | `rowEstimate > 1,000,000` |
| +2 levels | `rowEstimate > 20,000,000` |
| +1 level | operation takes ACCESS EXCLUSIVE and table is read by another service (declared in hints) |

`estimatedSeconds` is only produced when `rowEstimate` is known **and** the statement is a rewrite; otherwise
`null`. A null is honest; a guess is not.

**Every finding carries a `safeAlternative`** where one exists:

- SS001 → expand/contract: stop reading the column, deploy, then drop in a later migration.
- SS003 → add a CHECK `(column IS NOT NULL) NOT VALID`, validate it, then SET NOT NULL where the
  server can use that proof. NOT VALID cannot be applied directly to NOT NULL; document locks per step.
- SS009 → `CREATE INDEX CONCURRENTLY`.
- SS006 → rename hint file, or expand/contract.

---

## 10. Repository layout

```
schemasentry/
├── src/schemasentry/
│   ├── cli.py              typer commands
│   ├── introspect.py       pg_catalog + information_schema readers
│   ├── snapshot.py         models, serialisation, deterministic ordering
│   ├── diff.py             structural comparison
│   ├── rules/              one module per rule id
│   ├── dialects/           postgres.py, mysql.py (M6)
│   ├── hints.py            rename and ownership hints
│   └── report/             markdown.py, json.py
├── tests/
│   ├── corpus/             the accuracy contract
│   ├── fixtures/           snapshot pairs
│   ├── unit/
│   └── integration/        real Postgres in docker
├── action/                 GitHub Action wrapper (M5)
└── docs/                   plan, architecture, rules, ADRs
```

---

## 11. Milestones

### M1 — Introspection and snapshot format

**Deliverable:** `snapshot` command producing a deterministic JSON snapshot from PostgreSQL 13–17.

**Acceptance criteria**

- [x] Captures tables, columns, types, nullability, defaults, identity, constraints, indexes, sequences
- [x] Two runs against an unchanged database produce byte-identical output
- [x] Read-only transaction; `statement_timeout` enforced
- [x] Row estimates are null, not zero, for unanalysed tables
- [x] Integration tests run against PG 13, 15 and 16 in CI
- [x] Unknown column types are preserved verbatim, not dropped

Status note: the integration suite passes against a real PostgreSQL 13.23, 15 and 16.16 server, run
locally with Docker on 2026-11-13. The CI workflow defines the same three-version matrix, and it has
executed: the first run on GitHub on 2026-11-13 passed against PostgreSQL 13, 15 and 16. Byte-identical
output requires a fixed `capturedAt`: use `--captured-at` or `SOURCE_DATE_EPOCH`, as the test suite
does. The snapshot format is pinned by `docs/schema/snapshot-v1.schema.json` and validated by the
test suite. ADR 0002 records the decisions made along the way, including the PostgreSQL 13 versus 14
difference in how an unanalysed table reports its row estimate.

### M2 — Comparison engine

**Deliverable:** `diff` command over two snapshot files with structural change detection.

**Acceptance criteria**

- [x] Added/removed tables, columns, constraints and indexes detected
- [x] Column order changes and renamed constraints do not produce false changes
- [x] Output is deterministic and sorted by (schema, table, object)
- [x] 20 fixture pairs with expected change sets, all passing
- [x] Comparison of a 500-table snapshot completes in under 10 s

M2 is complete and merged into `main`. Thirty pairs, real CLI/schema tests and live PG 13/15/16
checks pass. See ADR 0003 and docs/testing/m1-m2-validation.md. Diff compares tables/columns/constraints/
indexes; sequences, extensions, capture scope and uncaptured table properties remain outside this milestone.

Main CI [43553918501](https://github.com/shellghostt/schemasentry/actions/runs/43553918501) passed for this
baseline. PG13 remains compatibility coverage, not a recommendation to deploy an upstream unsupported version.

### M3 — Classification rules

**Deliverable:** rules SS001–SS007, validated rename hints and minimal SQL evidence parsing with corpus cases.

Status: **Complete on `feat/m3-implementation`, including branch and PR CI**.
Follow [M3 requirements](phases/M3.md) and [ADR 0004](adr/0004-m3-classification-evidence.md);
public reports and thresholds remain M4. SS-013–SS-020, including SS-013A, are implemented.

**Acceptance criteria**

- [x] Every rule has at least 3 corpus cases: one positive, one negative, one edge
- [x] SS002 type matrix implemented with section 9's policy and ADR 0004's evidence prerequisites
- [x] SS006 requires explicit hints; without them structural drop/add remains and SS001 classifies removal
- [x] Unanalysable statements are reported, never silently ignored
- [x] Corpus suite runs in under 60 s
- [x] NOT NULL/default/volatility evidence and version caveats are covered without guessing
- [x] Existing structural `diff` JSON and exit 0 remain unchanged

[M3 validation](testing/m3-validation.md) maps each gate to its tests. Native `make test` passed with
279 tests, 8 intentional offline skips and 92% coverage in 46.48 s. Live PG13.23/15.20/16.16 suites
each passed 68 tests with the same 8 offline skips. Lint, types, build, audit and runtime smoke passed.
Branch CI [43742250735](https://github.com/Shellghostt/SchemaSentry/actions/runs/43742250735) and PR CI
[43742445042](https://github.com/Shellghostt/SchemaSentry/actions/runs/43742445042) passed all six jobs
for `b73f9db`: Python 3.12/3.13, PG13/15/16 integration and dependency audit.

### M4 — Risk scoring and reports

**Deliverable:** rules SS008–SS010, risk levels, Markdown and JSON reports, exit codes, `compare` and `explain`.

**Acceptance criteria**

- [ ] Risk modifiers applied and unit-tested at boundary row counts
- [ ] `estimatedSeconds` is null unless row count and rewrite are both known
- [ ] Markdown report matches the documented template, including safe alternatives
- [ ] Exit codes match section 8 exactly
- [ ] Report is byte-identical across runs for identical input

### M5 — GitHub Action

**Deliverable:** Action that snapshots, compares against a committed baseline, and fails the check.

**Acceptance criteria**

- [ ] Action runs in under 60 s on a 500-table schema
- [ ] Report is posted as a PR comment, updated in place, not duplicated
- [ ] Threshold configurable via `fail-on`
- [ ] Secrets never appear in logs or comments
- [ ] Baseline convention documented: `db/schema/snapshot.json` on the default branch

### M6 — MySQL and performance analysis

**Deliverable:** MySQL dialect, lock estimation improvements, v1.0.0.

**Acceptance criteria**

- [ ] Dialect interface proven by a second implementation
- [ ] MySQL-specific rules documented separately, no silent divergence
- [ ] Corpus exceeds 100 cases and passes in CI
- [ ] Performance analysis on a 10M-row table documented with real timings
- [ ] `CHANGELOG.md` and README roadmap complete

---

## 12. Backlog

| ID | Task | Depends | Milestone |
|---|---|---|---|
| SS-001 | Typer CLI skeleton, config, exit-code helpers | — | M1 |
| SS-002 | Connection layer with read-only transaction | SS-001 | M1 |
| SS-003 | Snapshot Pydantic models | — | M1 |
| SS-004 | Table + column introspection | SS-002, SS-003 | M1 |
| SS-005 | Constraint and index introspection | SS-004 | M1 |
| SS-006 | Deterministic serialiser | SS-003 | M1 |
| SS-007 | Integration harness with PG 13/15/16 | SS-002 | M1 |
| SS-008 | Row estimate and size capture | SS-004 | M1 |
| SS-009 | Object matcher (stable keys) | SS-003 | M2 |
| SS-010 | Table and column diff | SS-009 | M2 |
| SS-011 | Constraint and index diff | SS-009 | M2 |
| SS-012 | Fixture pairs and golden diff tests | SS-010 | M2 |
| SS-013 | Rule framework + registry | SS-010 | M3 |
| SS-013A | Minimal SQL evidence parser with explicit unsupported results | SS-013 | M3 |
| SS-014 | SS001 drop column | SS-013 | M3 |
| SS-015 | SS002 type change matrix | SS-013 | M3 |
| SS-016 | SS003 not-null with validated-row evidence | SS-013 | M3 |
| SS-017 | SS004 missing fk index | SS-013 | M3 |
| SS-018 | SS005 locking statements | SS-013A | M3 |
| SS-019 | SS006 rename hints | SS-013 | M3 |
| SS-020 | SS007 default volatility/version evidence | SS-013A | M3 |
| SS-020A | SS008–SS010 constraints/indexes/enums and corpus cases | SS-020 | M4 |
| SS-021 | Risk scoring engine | SS-014 | M4 |
| SS-022 | Markdown renderer | SS-021 | M4 |
| SS-023 | JSON renderer and determinism tests | SS-021 | M4 |
| SS-024 | `explain` command and rule docs | SS-013 | M4 |
| SS-025 | Corpus expansion to 60 cases | SS-020 | M4 |
| SS-026 | Broader migration parser integration for CI (minimal parser is SS-013A) | SS-013A | M5 |
| SS-027 | GitHub Action and PR comment | SS-022 | M5 |
| SS-028 | Baseline convention and docs | SS-027 | M5 |
| SS-029 | MySQL dialect | SS-009 | M6 |
| SS-030 | Lock estimation on real datasets | SS-021 | M6 |

---

## 13. Testing strategy

- **Corpus:** `tests/corpus/<nnnn>-<slug>/` with `before.sql`, `migration.sql`, `expected.json`,
  `notes.md`. This is the contract. New rules start with a failing case.
- **Snapshot determinism:** capture twice, assert byte equality.
- **Real database:** integration tests use Docker Postgres; no mocked catalog queries — the whole point is
  that real catalogs are messy.
- **Negative cases:** every rule needs a "does not fire" case to prevent false positives.

**Targets:** snapshot of 500 tables < 5 s; diff < 10 s; full corpus < 60 s; memory < 300 MB.

---

## 14. Security and threat model

| Threat | Mitigation |
|---|---|
| Tool writes to the database | Read-only transaction, no DDL/DML in the codebase, test asserts no write statements |
| Credentials leak into reports | DSN never serialised; connection info reduced to host/database name |
| Malicious SQL in a migration file | Files are parsed, never executed |
| Supply chain | `pip-audit` in CI, pinned lockfile |
| Report injection in PR comments | Markdown escaped; no raw SQL in comment bodies beyond a fenced block |

---

## 15. Risks and open questions

| Risk | Impact | Mitigation |
|---|---|---|
| Static prediction diverges from real DDL | Wrong risk score | Report `confidence`; corpus grows with every bug report |
| Lock behaviour differs across PG versions | Bad estimates | Version-aware rule table, cited in docs |
| False positives annoy users | Tool disabled in CI | Conservative defaults, `--fail-on`, safe alternatives in every finding |
| Dialect abstraction leaks | MySQL becomes a fork | Dialect interface defined in M1, proven in M6 |

**Open questions:**

1. Should baseline snapshots be stored in the repo or as CI artifacts? *Current: repo, reviewable.*
2. Do we support `--fail-on medium`? *Current: yes, thresholds are a user policy.*
3. Is a hints file the right mechanism for renames, or should we infer from column comments? *Current: hints
   file, explicit and reviewable.*

---

## 16. Anti-hallucination contract

**Facts:** the package imports, `schemasentry version` prints `0.1.0`, and `schemasentry snapshot`
captures a deterministic JSON snapshot of a PostgreSQL 13 to 17 database through a read-only
transaction. M2 compares snapshot structure with deterministic JSON and 30 fixture pairs. There is
no classification rule, risk score, Markdown report or migration corpus case.

**Rules:**

1. Never say a migration is safe. Report risk and evidence.
2. A rule without a corpus case does not exist, even if the code exists.
3. Never invent `estimatedSeconds`. Null is the correct answer when row counts are unknown.
4. Do not claim support for a PostgreSQL version that is not in the CI matrix.
5. SQL that cannot be modelled must appear as `unanalysable_statement`, never be dropped.
6. Update the rule table, README roadmap and CHANGELOG in the same pull request.

**Glossary:**

| Term | Meaning |
|---|---|
| Snapshot | Deterministic JSON representation of schema state. |
| Baseline | A snapshot committed as the reference for CI. |
| Change | One structural difference between two snapshots. |
| Finding | A change plus a rule verdict and risk. |
| Risk | Highest applicable severity after modifiers. |
| Unanalysable | A statement the parser cannot model; always surfaced. |
| Hint | A user declaration (e.g. rename) that rules may rely on. |

---

## 17. Handoff protocol

1. Read sections 0, 3 and 9.
2. Run `make bootstrap`, `make test`, `make lint` and `make type`; use a disposable server for live evidence.
3. M1/M2 are merged and M3 is complete on the feature branch with CI. Read [M3 requirements](phases/M3.md),
   [ADR 0004](adr/0004-m3-classification-evidence.md) and [validation](testing/m3-validation.md) before M4 work.
4. Before changing a rule, add the corpus case that proves the change.
5. If a finding is wrong, the fix is a new case plus a rule change — never a special case in the renderer.
