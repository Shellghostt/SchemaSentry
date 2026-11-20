# SchemaSentry

> Detect dangerous database schema changes before they reach production.

![status](https://img.shields.io/badge/status-M4_verified-green)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
![Python](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)

**M4 is implemented and verified on `feat/m4-implementation`, including GitHub CI.**
Review [PR #4](https://github.com/Shellghostt/SchemaSentry/pull/4); it is open and not merged.
SchemaSentry assesses supplied/observed PostgreSQL schema states with ten rules, explicit evidence,
deterministic risk scoring and Markdown/JSON reports. M1–M3 are merged with passing CI.
See the [M4 validation record](docs/testing/m4-validation.md) for the measured gates and limitations.

## Why this exists

Migration reviews are done by eye. "ALTER TABLE users ALTER COLUMN age TYPE varchar" looks
harmless in a pull request and can cause a long outage. SchemaSentry compares a baseline with a supplied
or observed after state, classifies changes, and explains policy risk. An after state captured in staging
can support review before production deployment. Migration SQL is evidence; SchemaSentry never applies it
or predicts a future schema.

## Capabilities

| Capability | Milestone | Status |
|---|---|---|
| Capture a schema snapshot | M1 | **Done** |
| Compare schema snapshots | M2 | **Done (merged)** |
| Classify removed columns, including removed-table columns | M3 | **Implemented (internal API)** |
| Classify incompatible type changes | M3 | **Implemented (internal API)** |
| Separate declared DDL locks, scans and rewrites | M3 | **Implemented (internal API)** |
| Flag FK columns without proven supporting index coverage | M3 | **Implemented (internal API)** |
| Classify NOT NULL additions using validated evidence | M3 | **Implemented (internal API)** |
| Validate explicit column rename hints | M3 | **Implemented (internal API)** |
| Distinguish known volatile defaults from unknown functions | M3 | **Implemented (internal API)** |
| Classify CHECK/FK validation, index builds and enum membership | M4 | **Implemented** |
| Score risk with known size/FK modifiers and explicit unknowns | M4 | **Locally verified** |
| Markdown/JSON reports and `compare`, `rules`, `explain` | M4 | **Locally verified** |
| GitHub Actions integration | M5 | Not started |
| MySQL support | M6 | Not started |
| Migration performance analysis | M6 | Not started |

## Architecture

```mermaid
flowchart LR
    DB[(Database)] --> INTRO[Read-only capture]
    INTRO --> SNAP[Before and after snapshots]
    SNAP --> CMP[Structural comparator]
    SNAP --> CLASS[SS001-SS010 assessment]
    CMP --> CLASS
    MIG[Migration file] --> PARSE[Bounded SQL evidence]
    PARSE --> CLASS
    HINT[JSON rename hints] --> VALIDATE[One-to-one validation]
    VALIDATE --> CLASS
    CLASS --> RISK[Risk scoring and public reports]
```

Full reasoning, data model, API surface and failure behaviour are in [docs/PLAN.md](docs/PLAN.md).

## Engineering challenge

Understanding semantic database changes instead of comparing SQL text. Two migrations can
produce identical schemas with completely different SQL, and one innocuous-looking statement can rewrite a
table of forty million rows.

## Quickstart

Requires Python 3.12+ and a PostgreSQL 13 to 17 server (the integration suite uses Docker).

```bash
make bootstrap
.venv/Scripts/python -m schemasentry version   # Windows
.venv/bin/python -m schemasentry version         # macOS / Linux
```

A disposable database for local work:

```bash
make db-up      # docker compose, postgres:16 on port 55432
```

Capture a snapshot:

```bash
export SCHEMASENTRY_DATABASE_URL="postgresql://schemasentry:schemasentry@localhost:55432/schemasentry"
schemasentry snapshot --output snapshot.json
```

The JSON goes to stdout when `--output` is omitted, so it pipes cleanly:

```bash
schemasentry snapshot --schema public | jq '.tables[].name'
```

Real output from a local PostgreSQL 16 (abridged to the first column and the sequence):

```json
{
  "schemaVersion": 1,
  "dialect": "postgres",
  "serverVersion": "16.16",
  "capturedAt": "2026-11-13T10:00:00Z",
  "database": "schemasentry",
  "schemas": ["public"],
  "tables": [
    {
      "schema": "public",
      "name": "accounts",
      "rowEstimate": null,
      "totalBytes": 16384,
      "columns": [
        {
          "name": "id",
          "ordinal": 1,
          "type": "bigint",
          "normalisedType": "bigint",
          "length": null,
          "nullable": false,
          "default": "nextval('accounts_id_seq'::regclass)",
          "identity": false,
          "generated": null,
          "generationExpression": null
        }
      ],
      "constraints": [],
      "indexes": []
    }
  ],
  "sequences": [
    {
      "schema": "public",
      "name": "accounts_id_seq",
      "dataType": "bigint",
      "startValue": 1,
      "incrementBy": 1,
      "cycle": false
    }
  ],
  "extensions": ["plpgsql"]
}
```

Every legacy field is present. Optional M4 `catalogEvidence` is omitted by default and captured with
`--analysis-evidence`. `null` means "unknown", never "zero": a table nobody has analysed has
`rowEstimate: null`, and a user-defined type keeps its name instead of being dropped. The format is
pinned by [docs/schema/snapshot-v1.schema.json](docs/schema/snapshot-v1.schema.json) and validated by
the test suite.

For a byte-identical file, fix the timestamp:

```bash
schemasentry snapshot --captured-at 2026-11-13T10:00:00Z --output snapshot.json
```

`SOURCE_DATE_EPOCH` works too. Exit codes: `0` success, `3` tool error (connection, unsupported server
version), `4` invalid usage. `snapshot` and structural `diff` retain these exits; M4 `compare` adds risk exits.

Compare two snapshots offline:

```bash
schemasentry diff --before tests/fixtures/05-column-removed/before.json --after tests/fixtures/05-column-removed/after.json
```

Successful diffs exit 0 even when changes exist; this is structural evidence, not a risk verdict.
Output follows [the diff schema](docs/schema/diff-v1.schema.json), ignores column order/statistics,
and suppresses constraint/index renames with unchanged definitions. Use matching capture scopes and
the same collector version. Legacy snapshots warn about incomplete evidence. Sequence/extension
changes and uncaptured table properties are outside M2. See [ADR 0003](docs/adr/0003-m2-structural-comparison.md).

Tests include 30 exact fixture pairs, real CLI subprocesses, a 500-table performance check and live
PostgreSQL 13/15/16 cases. [Validation results](docs/testing/m1-m2-validation.md) record the commands.
Install hashed runtime dependencies with `pip install --require-hashes -r requirements.lock`, then
install development tools with `pip install -e ".[dev]"`. CI and the runtime image use this lock.

## Internal M3 classification

M3 adds a library API; the `diff` command retains its structural output and exit behavior:

```python
from pathlib import Path

from schemasentry.classification import classify
from schemasentry.diff import load_snapshot
from schemasentry.hints import load_hints
from schemasentry.migration import load_migration

result = classify(
    load_snapshot(Path("before.json")),
    load_snapshot(Path("after.json")),
    migration=load_migration(Path("migration.sql")),  # parsed as data
    hints=load_hints(Path("hints.json")),  # optional strict JSON v1
    default_schema="public",  # explicit binding for unqualified SQL
)
print(result.model_dump_json(indent=2))
```

Omit optional migration or hints arguments when absent. Missing or unsupported evidence produces
notices; hints declare a rename without proving data preservation. SQL files are capped at 256 KiB,
128 statements, 20,000 tokens and nesting 64. Hint files are capped at 64 KiB and 128 mappings.
Findings contain base severity, confidence, evidence and limitations, with separate lock/scan/rewrite
effects when supported. Confirmed effects use matching PostgreSQL 13/15/16 version evidence;
unknown casts, functions and uncaptured table properties remain uncertain. No duration is predicted.
See [ADR 0004](docs/adr/0004-m3-classification-evidence.md) and the
[M3 validation record](docs/testing/m3-validation.md) for 59 reviewed cases, live evidence and skips.

## Public M4 assessment

Capture M4 baselines and after states with catalog evidence:

```bash
schemasentry snapshot --schema public --analysis-evidence --output before.json
# Capture the state observed after the migration was applied externally, for example in staging.
schemasentry snapshot --schema public --analysis-evidence --output after.json
schemasentry compare --baseline before.json --after after.json --migration migration.sql --format markdown
```

The after file makes comparison fully offline, including when `SCHEMASENTRY_DATABASE_URL` is set.
For a read-only live after state, replace `--after after.json` with `--database URL`, or omit both choices
to use the environment URL. Live capture uses the baseline's declared schema scope. Explicit `--after`
conflicts with `--database`/`--captured-at`. An explicit empty database argument is invalid usage.

Optional `--hints FILE` uses existing rename-hints v1. `--default-schema public` binds unqualified SQL
names; `--threshold low|medium|high|critical` defaults to high. `--format json` selects the
[report v1 schema](docs/schema/report-v1.schema.json); `--output FILE` publishes atomically and protects
selected inputs from overwrite. Both formats retain provenance, base/final risk, confidence, effects,
modifiers, alternatives, notices and limitations. `estimatedSeconds` is always null in M4.

| Exit | Meaning for `compare` |
|---|---|
| 0 | Complete analysis below threshold; no general safety claim |
| 1 | Complete report crosses the threshold without critical risk |
| 2 | Complete report contains critical/blocking risk, regardless of threshold |
| 3 | Tool/input/output failure or incomplete required analysis |
| 4 | Invalid usage or policy arguments |

Complete assessment requires both M4 catalog extensions and matching confirmed PostgreSQL 13/15/16
version evidence. Legacy omission, unsupported syntax, unresolved targets and missing enum/dependency
facts remain explicit incomplete results. Unknown optional size/FK/reader modifiers do not lower severity.
Risk adds distinct known size/FK contributions to base rank, capped at critical; overall risk is the maximum.
Read [ADR 0005](docs/adr/0005-m4-risk-and-report-contract.md) for exact boundaries and supported rule semantics.

Inspect definitions offline:

```bash
schemasentry rules --json
schemasentry explain SS009
make check-docs
```

The [ten rule pages](docs/rules/README.md) are generated from this metadata with `make docs`.
Existing snapshot/SQL/hint byte limits remain. M4 additionally bounds combined objects at 200,000,
findings at 10,000, notices at 2,048, dynamic strings at 256 KiB and complete reports at 16 MiB.
Rejected inputs or output failures do not publish a partial success report.

## Repository layout

| Path | Purpose |
|---|---|
| `src/schemasentry/cli.py` | Snapshot, diff, compare, rules, explain and version commands |
| `src/schemasentry/diff.py` | Pure structural comparator and bounded snapshot loader |
| `src/schemasentry/classification.py` | Internal deterministic SS001–SS007 classification |
| `src/schemasentry/evidence.py` | Frozen findings, notices and separate operation effects |
| `src/schemasentry/migration.py` | Bounded SQL evidence parser; never executes migration input |
| `src/schemasentry/hints.py` | Strict JSON v1 column rename declarations |
| `src/schemasentry/config.py` | Environment variables, timestamp resolution, DSN redaction |
| `src/schemasentry/db.py` | Read-only connection, statement timeout |
| `src/schemasentry/introspect.py` | Capture orchestration: connect, dialect, snapshot |
| `src/schemasentry/snapshot.py` | Snapshot model, deterministic ordering and serialisation |
| `src/schemasentry/dialects` | One module per engine; PostgreSQL implemented, MySQL in M6 |
| `src/schemasentry/rules` | SS001–SS010 rules; original seven-rule M3 registry preserved |
| `src/schemasentry/catalog_models.py`, `catalog_capture.py` | Versioned, scoped M4 facts and read-only collection |
| `src/schemasentry/m4_migration.py` | Bounded M4 evidence extension and immutable legacy classification view |
| `src/schemasentry/assessment.py` | Pure scoring, completeness, provenance and threshold exits |
| `src/schemasentry/report.py`, `report_io.py` | Escaped/bounded renderers and checked atomic publication |
| `src/schemasentry/registry.py`, `docs/rules` | Offline metadata and generated rule pages |
| `docs/schema` | Committed JSON schemas, enforced by tests |
| `tests/unit` | Model, configuration and CLI tests, no database needed |
| `tests/integration` | Tests against a real PostgreSQL server |
| `tests/corpus` | 59 independently reviewed M3 classification cases |
| `tests/corpus-m4`, `tests/golden` | Nine reviewed M4 cases and complete/hostile Markdown goldens |
| `scripts/profile_m3.py` | Repeated synthetic parser/diff/classifier memory workload |
| `scripts/profile_m4.py`, `scripts/check_runtime.py` | Owned 500-table/memory profile and installed-runtime oracle checks |
| `action` | GitHub Action wrapper (M5) |

## Roadmap

M3 is **complete and merged** through [PR #3](https://github.com/Shellghostt/SchemaSentry/pull/3), with
successful [main CI](https://github.com/Shellghostt/SchemaSentry/actions/runs/43744133540). Read the
[M3 acceptance gates](docs/phases/M3.md), [validation record](docs/testing/m3-validation.md)
and [development-tool audit](docs/DEVELOPMENT-TOOLS.md) before debugging.
The [M4 requirements](docs/phases/M4.md), accepted [scoring/report ADR](docs/adr/0005-m4-risk-and-report-contract.md)
and [validation](docs/testing/m4-validation.md) document implemented SS008–SS010 and public assessment.
All local gates and the Python/PG GitHub CI matrices passed for `de44a2b`:
[branch CI](https://github.com/Shellghostt/SchemaSentry/actions/runs/44797738740) and
[PR CI](https://github.com/Shellghostt/SchemaSentry/actions/runs/44797752285), six jobs each.
M4 is not merged or released.

| Milestone | Deliverable | Status |
|---|---|---|
| M1 | PostgreSQL introspection and normalised snapshot format | **Done** (v0.1.0) |
| M2 | Snapshot storage and structural comparison | **Done (merged)** |
| M3 | Internal classification rules SS001-SS007 | **Done (merged)** |
| M4 | SS008–SS010, scoring, reports and public commands | Verified locally and in CI; PR #4 open |
| M5 | GitHub Action and CI integration | Not started |
| M6 | MySQL support and migration performance analysis | Not started |

This roadmap mirrors [docs/PLAN.md](docs/PLAN.md) section 11. If the two disagree, the plan is correct and
the README is a bug.

## Project standards

- Conventional Commits, Semantic Versioning, `main` is always green.
- Every release is produced by CI, never by a laptop.
- Status claims must match reality. Unbuilt features are marked "Not started", not "coming soon".
- Decisions are recorded as ADRs in [docs/adr/](docs/adr/).

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/PLAN.md](docs/PLAN.md) first. Issues labelled
`good first issue` are scoped for a first pull request.

## Using an AI assistant on this repository

Read [docs/PLAN.md](docs/PLAN.md) end to end, including the machine context block at the top. It states
what exists, what does not, and which claims are forbidden. Do not describe planned behaviour as
implemented behaviour.

## License

Apache License 2.0 - see [LICENSE](LICENSE).
