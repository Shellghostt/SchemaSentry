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
updated: 2026-11-21
---

# SchemaSentry — Implementation Plan

> **This file is the specification.** Accuracy claims are defined by `tests/corpus/`, not by opinion.

---

## 0. Machine context

M1–M3 are complete and merged into `main`. [M3 PR #3](https://github.com/Shellghostt/SchemaSentry/pull/3)
merged at `3c76af15670643640cb0efef4d1ab9a49956ca73`, with successful
[main CI](https://github.com/Shellghostt/SchemaSentry/actions/runs/43744133540).
[ADR 0004](adr/0004-m3-classification-evidence.md) defines the internal
evidence API. The [M3 requirements](phases/M3.md) and [validation record](testing/m3-validation.md)
record 59 reviewed cases, live PG13/15/16 evidence and canonical local gates.
The [development-tool audit](DEVELOPMENT-TOOLS.md) records profiling limits. No new release is claimed.
M4 is **implemented and locally verified on `feat/m4-implementation`**. Accepted
[ADR 0005](adr/0005-m4-risk-and-report-contract.md), [M4 requirements](phases/M4.md) and
[validation](testing/m4-validation.md) define the ten-rule public assessment, catalog extension and
report policy. Final GitHub Python/PG CI awaits publication. M4 is not merged or released.

```yaml
project: SchemaSentry
status: mvp
version: 0.1.0
builds: true
functional: true               # M4 assessment is locally verified; GitHub CI is pending

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
  - structural exits 0/3/4 and public assessment exits 0/1/2/3/4
  - internal deterministic classification registry SS001-SS007 with evidence and limitations
  - bounded SQLGlot PostgreSQL evidence parser with visible unsupported/errors and no SQL execution
  - strict JSON v1 one-to-one column rename hints inside classification
  - 59 reviewed corpus cases and disposable live PG13/15/16 classification evidence
  - native Python lifecycle profiling and installed Docker runtime checks
  - opt-in versioned M4 catalog evidence for constraints, enums, relations and incoming FKs
  - SS008-SS010 and ten-rule M4 assessment; seven-rule M3 classification remains compatible
  - deterministic capped risk scoring with explicit unknown modifiers and null estimatedSeconds
  - public compare, rules and explain with offline/live input precedence
  - bounded versioned JSON and escaped Markdown with checked atomic output
  - 68 reviewed corpus cases and complete/hostile Markdown goldens
  - registry-derived rule pages and schema drift checks; real package build target

not_implemented:
  - migration-to-snapshot prediction and broader parser integration
  - ownership hints and hint format v2
  - github action
  - mysql support

source_of_truth:
  scope_and_rules: docs/PLAN.md        # this file, section 9
  accuracy_contract: tests/corpus/ and tests/corpus-m4/
  architecture: docs/ARCHITECTURE.md
  decisions: docs/adr/
  status: README.md#roadmap
  snapshot_contract: docs/schema/snapshot-v1.schema.json
  report_contract: docs/schema/report-v1.schema.json

forbidden_claims:
  - "detects all dangerous migrations"
  - "safe" or "guaranteed" about any migration
  - support for a database version not in the support matrix
  - a rule that has no corpus case

if_uncertain:
  - add a corpus case before changing a rule
  - if lock behaviour is version-dependent, cite the PostgreSQL version in the rule
  - estimatedSeconds stays null without a separately accepted calibrated model and required evidence
```

---

## 1. What this is

A CLI that compares a baseline with supplied/observed after-state snapshots, classifies changes and
explains policy risk. Staging captures can support review before production deployment. SQL is bounded
secondary evidence; no command applies it or predicts an after state.

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

PostgreSQL only. Snapshot, compare two snapshots, classify SS001–SS010, score risk, Markdown and JSON
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

The implemented M4 flow compares supplied snapshots or an observed live after state. Migration-directory
handling remains M5; future prediction requires a separately accepted contract. Component responsibilities
and the immutable legacy evidence view are in [ARCHITECTURE.md](ARCHITECTURE.md).

```mermaid
flowchart LR
    DB[(Database)] --> INTRO[Read-only catalog capture]
    MIG[One migration file] --> PARSE[Bounded SQL evidence]
    INTRO --> NORM[Before and after snapshots]
    NORM --> CMP[Structural comparator]
    CMP --> CLASS[Change classification]
    NORM --> CLASS
    PARSE --> CLASS
    CLASS --> RISK[Risk scoring]
    RISK --> REP[Markdown / JSON report]
    REP --> CI[CI exit code]
```

`diff --before FILE --after FILE` retains structural JSON and success exit 0. Public
`compare --baseline FILE (--after FILE | --database URL)` applies M4 classification/scoring to supplied
or observed states. Unsupported SQL stays visible; it cannot become a silently clean report.

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
and the size modifier is explicitly unknown instead of guessed. Confidence remains a separate
classification-evidence property.

The machine-readable contract is `docs/schema/snapshot-v1.schema.json`, and a test validates a real
captured snapshot against it. It adds evidence fields to the example above, each because the shorter form
would state something false: `generationExpression` on a generated column, `referencedTable` and
`referencedColumns` on a foreign key, and `expression` on an index. See ADR 0002.

**Public report v1 (abridged):**

The full [report schema](schema/report-v1.schema.json) includes required provenance, effects, evidence,
modifiers, alternatives and notices. Every nullable output field is present. M3 corpus files retain their
separate internal finding format; the public report follows accepted [ADR 0005](adr/0005-m4-risk-and-report-contract.md).

```json
{
  "schemaVersion": 1,
  "policyVersion": 1,
  "toolVersion": "0.1.0",
  "analysisStatus": "complete",
  "threshold": "high",
  "overallRisk": "critical",
  "findings": [
    {
      "ruleId": "SS001",
      "baseSeverity": "critical",
      "finalRisk": "critical",
      "confidence": "high",
      "object": "email",
      "kind": "column_removed",
      "estimatedSeconds": null
    }
  ]
}
```

---

## 8. Command surface and exit codes

```
schemasentry snapshot  --database URL --output snap.json [--analysis-evidence]
schemasentry compare   --baseline snap.json (--after after.json | --database URL) [--migration migration.sql]
                       [--hints hints.json] [--default-schema public]
                       [--format markdown|json] [--threshold low|medium|high|critical] [--output FILE]
schemasentry diff      --before a.json --after b.json
schemasentry explain   <rule-id>
schemasentry rules     [--json]
schemasentry version
```

| Exit code | Meaning |
|---|---|
| 0 | Complete analysis below `--threshold` (default high); no general safety claim |
| 1 | Complete report crosses the threshold without critical risk |
| 2 | Complete report has critical/blocking risk, regardless of threshold |
| 3 | Tool/input/output failure or incomplete required analysis |
| 4 | Invalid usage |

For live capture, `SCHEMASENTRY_DATABASE_URL` supplies the URL when no explicit database is selected.
Explicit `--after` is fully offline and ignores that environment URL; it conflicts with explicit database/
captured-at arguments. Explicit empty database arguments are usage errors. Capture remains read-only
REPEATABLE READ with `statement_timeout = 5s`; live compare uses the baseline scope.

Snapshot/diff/version and the default seven-rule M3 library API retain their meanings. Diff exits 0 even
with changes. M4 adds compare/rules/explain; incomplete analysis precedes critical and threshold exits.
Snapshots remain capped at 64 MiB, migration SQL at 256 KiB/128 statements/20,000 tokens/64 levels and
hints at 64 KiB/128 mappings. M4 additionally caps combined objects at 200,000, findings at 10,000,
notices at 2,048, dynamic strings at 256 KiB and either report at 16 MiB. Output is checked and atomic.
See [M4 validation](testing/m4-validation.md). Directory input remains M5.

---

## 9. Rules

Stable IDs. [Rule pages](rules/README.md) derive from the same metadata as offline commands.
All ten have reviewed corpus coverage. The table lists policy defaults; some findings use conditional severities.

| ID | Detects | Base severity | Notes |
|---|---|---|---|
| SS001 | Column removed | critical | Breaks readers still referencing that column |
| SS002 | Column type changed | high | Some changes are safe; see table below |
| SS003 | NOT NULL added without validated evidence that existing rows satisfy it | high | Defaults are not proof; validated CHECK evidence can avoid a scan on supported versions |
| SS004 | Missing index on a foreign key | medium | Scaled by table size; write-path amplification |
| SS005 | Locking or rewriting statement | high | `ALTER TYPE`, `SET NOT NULL`, `ADD COLUMN ... DEFAULT`, `VACUUM FULL` |
| SS006 | Rename appearing as drop + add | high | Requires a rename hint file, otherwise data loss risk |
| SS007 | Known volatile default or unknown function volatility | medium | Nonliteral does not imply volatile; PG11+ non-volatile ADD COLUMN defaults can avoid rewrite |
| SS008 | Eligible CHECK/FK addition or validation | high | Ordinary relation/validation facts and requested SQL must bind; NOT VALID retains locks |
| SS009 | Index build mode and blocking requests | high | Ordinary build blocks writes; forbidden concurrent transaction/partition requests are critical |
| SS010 | Known enum membership removal or rename | critical | Removal is critical; supported rename is high; no direct DROP VALUE |

**Type-change nuance for SS002** (the rule must not cry wolf):

| Change | Verdict |
|---|---|
| `varchar(50)` → `varchar(100)` | No SS002 finding when the reviewed evidence prerequisites hold; no general safety claim |
| `varchar(100)` → `varchar(50)` | high, data truncation |
| `int` → `bigint` | medium, table rewrite |
| `bigint` → `int` | high, overflow risk |
| `text` → `varchar(n)` | high, needs validation query |
| `timestamp` → `timestamptz` | high, silent timezone reinterpretation |
| `numeric(p,s)` widening | medium; conversion/scan/rewrite depends on typmod and server evidence |

Base severities are policy; cast/lock/rewrite claims require version-specific evidence. USING expressions,
unknown types and user-function volatility must not be treated as safe by inference. See [M3 requirements](phases/M3.md).

**Implemented risk policy v1.** Accepted [ADR 0005](adr/0005-m4-risk-and-report-contract.md) defines
`min(3, base rank + size contribution + FK contribution)`, with low/medium/high/critical ranks 0/1/2/3.
Overall risk is the maximum scored finding, or null with no findings. Confidence and unknown prerequisites
remain separate; optional modifier gaps do not manufacture a bump or lower base severity.

| Modifier | Condition |
|---|---|
| +1 level | At least two distinct incoming named FKs target the finding's captured table, including outside-schema sources |
| +1 level | `1,000,000 < rowEstimate <= 20,000,000` |
| +2 levels | `rowEstimate > 20,000,000` |
| Unavailable under hints v1 | Service-reader lock modifier needs separately accepted ownership evidence |

`estimatedSeconds` requires a supported rewrite, relevant size evidence **and** a measured/documented
estimation model; row estimates alone cannot produce seconds. It remains null in M4 without that model.
The existing rename-hints v1 cannot declare service readers. See [M4 requirements](phases/M4.md) for
size-tier boundaries, missing metadata, confidence and modifier deduplication.

**Every finding carries a `safeAlternative`** where one exists:

- SS001 → expand/contract: stop reading the column, deploy, then drop in a later migration.
- SS003 → add a CHECK `(column IS NOT NULL) NOT VALID`, validate it, then SET NOT NULL where the
  server can use that proof. NOT VALID cannot be applied directly to NOT NULL; document locks per step.
- SS009 → `CREATE INDEX CONCURRENTLY` where supported and outside an explicit transaction block;
  document extra work, invalid-index cleanup and partition/version restrictions.
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
│   ├── hints.py            rename-hints v1; ownership unavailable
│   ├── catalog_models.py  versioned M4 facts and consistency validation
│   ├── catalog_capture.py read-only bounded evidence queries
│   ├── m4_migration.py    M4 parser and immutable legacy evidence view
│   ├── assessment.py      scoring, completeness, provenance and exits
│   ├── registry.py        offline metadata and generated rule pages
│   ├── report.py          JSON and escaped Markdown
│   └── report_io.py       checked/atomic publication
├── tests/
│   ├── corpus/             59 M3 oracles
│   ├── corpus-m4/          nine reviewed M4 oracles
│   ├── golden/             complete/hostile Markdown templates
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

Status: **Complete and merged into main**, including branch, PR and merged-main CI.
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

Status: **Implemented and locally verified; final GitHub CI awaits publication.** Accepted
[ADR 0005](adr/0005-m4-risk-and-report-contract.md) was committed before code; the nine reviewed M4
oracles were committed before dependent rule implementation. SS-020A and SS-021–SS-025 are implemented.
Read [M4 requirements](phases/M4.md) and [validation](testing/m4-validation.md).

**Acceptance criteria**

- [x] SS008–SS010 have reviewed positive/negative/edge and unknown-evidence cases with correct PostgreSQL caveats
- [x] All 59 M3 cases are retained and nine new rule cases bring the corpus to 68; runtime stays <60 s
- [x] Risk formula, distinct modifiers and aggregation are tested at exact size/FK boundaries and unknown evidence
- [x] `estimatedSeconds` is null without a measured estimation model
- [x] Markdown report matches the complete/hostile goldens, including conditional alternatives
- [x] Public compare/explain/rules and incomplete-analysis exits match section 8; structural diff remains unchanged
- [x] Report is byte-identical across runs and shuffled validated catalog inputs
- [x] Public schema, input/output bounds, enum compatibility, read-only catalog and local canonical gates pass
- [ ] Final Python 3.12/3.13 and PostgreSQL 13/15/16 GitHub CI passes after publication

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
| SS-021 | Pure risk scorer and explicit completeness/threshold policy | SS-020A | M4 |
| SS-022 | Markdown renderer | SS-021 | M4 |
| SS-023 | Versioned JSON, determinism and public `compare` CLI | SS-021, SS-022 | M4 |
| SS-024 | Offline `explain`/`rules` commands and registry-derived docs | SS-020A | M4 |
| SS-025 | Corpus beyond 60 cases and end-to-end report/threshold checks | SS-020A, SS-023, SS-024 | M4 |
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
| Tool writes to the database | Product capture uses read-only transactions; generated fixture DDL runs only in owned test databases |
| Credentials leak into reports | Configured DSNs are absent; report provenance contains versions, capture timestamps and canonical input digests |
| Malicious SQL in a migration file | Files are parsed, never executed |
| Supply chain | `pip-audit` in CI, pinned lockfile |
| Report injection | Dynamic Markdown/HTML/links/fences and format/bidi controls are escaped; M5 publication remains future work |

---

## 15. Risks and open questions

| Risk | Impact | Mitigation |
|---|---|---|
| Requested SQL differs from observed states | Wrong effect inference | Bind evidence explicitly and report incomplete analysis |
| Lock behaviour differs across PG versions | Bad estimates | Version-aware rule table, cited in docs |
| False positives annoy users | Tool disabled in CI | Explicit confidence/threshold policy and conditional alternatives |
| Dialect abstraction leaks | MySQL becomes a fork | Dialect interface defined in M1, proven in M6 |

**Open questions:**

1. Should baseline snapshots be stored in the repo or as CI artifacts? *Current: repo, reviewable.*
2. Are medium thresholds supported? *Yes: M4 uses `--threshold medium`; M5's Action `fail-on` remains planned.*
3. Is a hints file the right mechanism for renames, or should we infer from column comments? *Current: hints
   file, explicit and reviewable.*

---

## 16. Anti-hallucination contract

**Facts:** the package imports, `schemasentry version` prints `0.1.0`, and `schemasentry snapshot`
captures a deterministic JSON snapshot of a PostgreSQL 13 to 17 database through a read-only
transaction. M2 compares snapshot structure with deterministic JSON and 30 fixture pairs. M3 adds
internal SS001–SS007 classification, bounded SQL/rename-hint evidence and 59 reviewed corpus cases.
M4 adds SS008–SS010, capped risk scoring, versioned reports and compare/rules/explain. Local gates and
installed-runtime checks pass; final GitHub CI is pending. It performs no migration execution or prediction.

**Rules:**

1. Never say a migration is safe. Report risk and evidence.
2. A rule without a corpus case does not exist, even if the code exists.
3. Never invent `estimatedSeconds`. It remains null throughout M4, including with known row estimates.
4. Do not claim support for a PostgreSQL version that is not in the CI matrix.
5. SQL outside the supported evidence subset stays visible and incomplete. A supported M4 statement
   supersedes only its own legacy unsupported location; other statements remain unanalysable.
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
2. Run `make bootstrap`, `make test`, `make lint`, `make type`, `make build`, `make check-docs` and
   `make audit`; use a disposable server for live evidence.
3. M1–M3 are merged with successful main CI. M4 is locally verified on its feature branch. Read
   [M4 requirements](phases/M4.md), accepted ADR 0005 and [validation](testing/m4-validation.md), then
   preserve the implemented [M3 contract](phases/M3.md). Final GitHub CI and merge remain pending.
4. Before changing a rule, add the corpus case that proves the change.
5. If a finding is wrong, the fix is a new case plus a rule change — never a special case in the renderer.
