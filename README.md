# SchemaSentry

> Detect dangerous database schema changes before they reach production.

![status](https://img.shields.io/badge/status-M3_classification-orange)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
![Python](https://img.shields.io/badge/python-3.12+-3776AB?logo=python&logoColor=white)

**Status: M3 implemented and locally verified on `feat/m3-implementation`; CI pending.**
SchemaSentry captures read-only PostgreSQL snapshots, compares their structure and provides internal
classification rules SS001–SS007 with bounded SQL evidence and explicit rename hints.
Risk scoring, public classification reports and migration-to-snapshot prediction remain later milestones.

## Why this exists

Migration reviews are done by eye. "ALTER TABLE users ALTER COLUMN age TYPE varchar" looks
harmless in a pull request and takes the site down for eleven minutes. SchemaSentry compares the schema
you have with the schema the migration will produce, classifies the difference, and scores the risk
before the migration runs.

## What it will do

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
| Estimate migration risk | M4 | Not started |
| Markdown and JSON reports | M4 | Not started |
| GitHub Actions integration | M5 | Not started |
| MySQL support | M6 | Not started |
| Migration performance analysis | M6 | Not started |

## Architecture

```mermaid
flowchart LR
    DB[(Database)] --> INTRO[Read-only capture]
    INTRO --> SNAP[Before and after snapshots]
    SNAP --> CMP[Structural comparator]
    SNAP --> CLASS[Internal SS001-SS007 classification]
    CMP --> CLASS
    MIG[Migration file] --> PARSE[Bounded SQL evidence]
    PARSE --> CLASS
    HINT[JSON rename hints] --> VALIDATE[One-to-one validation]
    VALIDATE --> CLASS
    CLASS -. M4 .-> RISK[Risk scoring and public reports]
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

Every field is always present. `null` means "unknown", never "zero": a table nobody has analysed has
`rowEstimate: null`, and a user-defined type keeps its name instead of being dropped. The format is
pinned by [docs/schema/snapshot-v1.schema.json](docs/schema/snapshot-v1.schema.json) and validated by
the test suite.

For a byte-identical file, fix the timestamp:

```bash
schemasentry snapshot --captured-at 2026-11-13T10:00:00Z --output snapshot.json
```

`SOURCE_DATE_EPOCH` works too. Exit codes: `0` success, `3` tool error (connection, unsupported server
version), `4` invalid usage. Codes `1` and `2` belong to M4 and remain unreachable through M3.

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

## Repository layout

| Path | Purpose |
|---|---|
| `src/schemasentry/cli.py` | Typer commands: snapshot, diff, version |
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
| `src/schemasentry/rules` | Fixed SS001–SS007 registry and conditional PostgreSQL semantics |
| `src/schemasentry/report` | Markdown and JSON renderers (M4; empty today) |
| `docs/schema` | Committed JSON schemas, enforced by tests |
| `tests/unit` | Model, configuration and CLI tests, no database needed |
| `tests/integration` | Tests against a real PostgreSQL server |
| `tests/corpus` | 59 independently reviewed M3 classification cases |
| `scripts/profile_m3.py` | Repeated synthetic parser/diff/classifier memory workload |
| `action` | GitHub Action wrapper (M5) |

## Roadmap

M3 is **implemented and locally verified; CI pending**. Read the
[M3 acceptance gates](docs/phases/M3.md), [validation record](docs/testing/m3-validation.md)
and [development-tool audit](docs/DEVELOPMENT-TOOLS.md) before debugging.

| Milestone | Deliverable | Status |
|---|---|---|
| M1 | PostgreSQL introspection and normalised snapshot format | **Done** (v0.1.0) |
| M2 | Snapshot storage and structural comparison | **Done (merged)** |
| M3 | Internal classification rules SS001-SS007 | **Implemented; CI pending** |
| M4 | Risk scoring, Markdown and JSON reports, exit codes | Not started |
| M5 | GitHub Action and CI integration | Not started |
| M6 | MySQL support and migration performance analysis | Not started |

This roadmap mirrors [docs/PLAN.md](docs/PLAN.md) section 12. If the two disagree, the plan is correct and
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
