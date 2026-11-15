# SchemaSentry M3 validation — 2026-11-15

M3 is implemented and locally verified on `feat/m3-implementation`, based on merged M2
`02cf7e5`. Production implementation: `da8d148`. [ADR 0004](../adr/0004-m3-classification-evidence.md)
was accepted and committed in `25072c8` before implementation. Reviewed corpus expectations were
committed before the rules; they were not generated from classifier output.
CI is pending. This record does not establish a merge or release.

## Scope

The internal `classify(before, after, *, migration=None, hints=None, default_schema=None)` API and
registry implement SS001–SS007. Results contain immutable, deterministic findings and evidence
notices. Lock acquisition, scans and rewrites are separate effects; base severity is policy.
Missing evidence, unsupported syntax, unmatched snapshots and unknown semantics remain visible.
Product paths parse migration files as data and never execute them.

M2 snapshot models, capture SQL, structural diff, CLI and all 30 old fixture pairs are unchanged.
Risk aggregation, public reports, thresholds, `compare`, `explain` and exit codes 1/2 remain M4.
Confirmed operation effects require matching version strings within the PG13/15/16 evidence matrix.
The existing PG13–17 capture range is unchanged. PG13 testing is compatibility evidence for an
upstream unsupported version, not a deployment recommendation.

## Environment and gates

Native Windows amd64, Python 3.12.10, SQLGlot 30.31.0, Pydantic 2.14.3, psycopg 3.3.9,
Ruff 0.17.5, mypy 2.4.1 and GNU Make. The existing runtime lock pins SQLGlot 30.31.0;
the package declaration now constrains it to `>=30.31,<30.32` because the evidence parser uses
that reviewed parser API. PyYAML remains declared but unused by the initial strict JSON hints.

| Check | Result |
|---|---|
| M3 unit corpus and defensive evidence tests | 104 passed in 2.61 s; repeated after the CI import correction, 104 passed in 2.28 s |
| PG16.16 `make integration` | 68 passed, 8 intentionally offline cases skipped, 10.15 s |
| PG15.20 `make integration` | 68 passed, 8 intentionally offline cases skipped, 6.98 s |
| PG13.23 `make integration` | 68 passed, 8 intentionally offline cases skipped, 7.85 s |
| Full native `make test`, PG16.16, with coverage | 279 passed, 8 skipped in 46.48 s; 92% statement coverage |
| Final `make lint` | Passed: Ruff checks and format check; 116 files already formatted |
| `ruff check --no-cache .` and `ruff format --check --no-cache .` | Passed after the CI import correction and README example formatting |
| `make type` | Passed: all 26 source files |
| `uv build` | Built wheel and source distribution |
| `uvx pip-audit --strict --disable-pip --require-hashes -r requirements.lock` | No known vulnerabilities found |
| `docker build -t schemasentry:m3-test .` | Passed with hashed runtime dependencies |
| Installed Docker runtime, network disabled and fixture mounts read-only | All 59 offline cases matched: 57 classifications and 2 expected hint errors; CLI version and exact M2 diff JSON/exit 0 passed |
| CodeGraph refresh and `git diff --check` | Passed; local index and generated artifacts stay ignored |
| GitHub CI | Pending; no remote result is claimed yet |

The 92% coverage result is below the historical M2 report's 96%. M3 adds defensive parsing,
unconfirmed target/version paths and deliberately narrow default/cast/CHECK semantics, with some
fallback branches still uncovered. The old fixtures and tests remain intact; coverage is reported
as measured rather than treating unknown branches as established behavior. The PR records this reduction.

## Acceptance mapping

| Requirement | Tests and reviewed evidence |
|---|---|
| Positive, negative and edge coverage for every SS001–SS007 | `test_every_rule_has_reviewed_positive_negative_edge_cases`, `test_reviewed_m3_corpus`; 59 cases under `tests/corpus/` |
| Type matrix, USING, typmods and version/cast uncertainty | SS002 corpus cases; `test_unconfirmed_versions_never_claim_no_rewrite`, `test_unsupported_intervening_sql_prevents_a_widening_negative` |
| NOT NULL defaults, pre-existing NULLs, retained validated CHECK proof and default volatility | SS003/SS007 corpus cases; `test_live_reviewed_m3_corpus`, `test_catalog_volatility_allowlist_matches_server`, `test_declared_default_does_not_override_a_different_observed_function` |
| FK key-prefix coverage, stock opclasses/collation, invalid/partial/expression/legacy indexes | SS004 corpus cases, including actual M2 key metadata and composite/reversed equality-key order; live capture/classification on all three servers |
| Strict rename hints, collisions, cycles and deterministic shuffled inputs | `test_hint_file_is_strict_versioned_json`, `test_hint_file_read_is_bounded`, `test_hints_cannot_hide_absent_endpoints_or_cycles`, `test_shuffled_inputs_and_hinted_attribute_changes`, `test_multiple_hint_and_table_order_is_deterministic`, `test_python_aliases_and_excessive_hint_mappings_are_rejected` |
| Bounded SQL with original locations and explicit unsupported/errors; no execution or SQL logging | `test_sql_order_locations_quotes_comments_and_wrappers`, `test_sql_strings_dollar_quotes_and_nested_comments_preserve_statement_slices`, `test_unsupported_and_invalid_sql_are_visible_without_logging`, `test_command_fallback_cannot_bypass_resource_limits`, `test_unsupported_alter_actions_never_keep_partial_operations`, `test_classifier_never_connects_or_executes_migration`, `test_classifier_modules_do_not_import_database_or_process_apis` |
| PostgreSQL identifier semantics and immutable results | `test_unquoted_identifiers_fold_ascii_without_changing_unicode`, `test_finding_and_nested_result_are_frozen`, exact repeated classification/structural serialization in every valid corpus case |
| Lock, scan and rewrite evidence | Live corpus verifies heap-file changes, `atthasmissing` fast defaults and ALTER locks; `test_vacuum_full_requests_access_exclusive` verifies the queued VACUUM FULL lock request |
| Existing read-only capture, structural JSON and CLI exits | Existing snapshot/diff tests and all 30 fixture pairs, live PG13/15/16 regression suite, installed-runtime structural CLI smoke |
| Corpus under 60 s and native runtime memory evidence | Unit corpus suite 2.61 s; full native suite 46.48 s; repeated lifecycle profile below |

## Live corpus and recorded skips

Each live corpus fixture creates a fresh `ss_m3_<uuid>` database, applies only committed synthetic SQL,
captures the actual catalog, then drops that exact owned database. The test requires a disposable
server account with database-creation permission. No user migration or user database is used.
Cases with pre-existing NULLs assert PostgreSQL SQLSTATE `23502` and unchanged actual schema;
classification then uses the explicitly desired after snapshot, not a claim that failed SQL succeeded.

There are 51 live cases and eight intentionally offline cases on every tested server:

| Case | Reason for offline evidence |
|---|---|
| 0014 | Untested classification server version |
| 0015 | Contradictory type/typmod metadata |
| 0021 | Legacy CHECK definition is absent |
| 0027 | Invalid index metadata |
| 0031 | Legacy index keys are absent |
| 0032 | Custom opclass semantics outside the reviewed stock catalog |
| 0052 | Default assignment cast is intentionally unproven |
| 0055 | Declared SQL type does not match the desired snapshot |

All eight are exercised offline. Cases 0042/0044 are expected hint errors and are counted as passed
only after the expected rejection. No test is skipped merely because a classification differs.
The server matrix supplies actual catalog volatility, rewrite/fast-default and lock evidence;
it does not cover every PostgreSQL version, type, function or inherited/partitioned table.

## Lifecycle and memory evidence

Command: `.venv/Scripts/python.exe scripts/profile_m3.py --cycles 6 --batches 3`.
The workload covers all 57 non-error cases; the two intentionally invalid hint cases are excluded.
Each cycle performs 171 complete parser, snapshot, diff, classifier and serialization lifecycles,
followed by GC: 1,026 measured lifecycles plus warmups. The warmed corpus completed in 0.0658663 s.

Cycle durations were 0.516–0.615 s. Post-GC RSS stayed between 53,370,880 and 53,460,992 bytes;
process peak RSS was 119,939,072 bytes, below the plan's 300 MB target in this workload.
Peak traced Python allocation was 254,677 bytes. Retained traced bytes increased from 656 to 2,924;
the largest differences were the profiler's stored sample records and tracemalloc bookkeeping.
The Windows memory API setup is cached to avoid adding fresh ctypes classes each cycle.

This is finite synthetic workload evidence, not a universal absence-of-leaks claim or a budget for
arbitrary input files. Raw profiles and test logs remain local under ignored `dist/`; MemGuard and
Java heap analyzers were not used as Python gates.

## Corrections during validation

- ADD COLUMN NOT NULL without a default, or with a NULL default, needs a scan on the tested versions.
  Ordinary defaults do not establish historical nonnull proof. Independently reviewed default
  assignment cases retain uncertainty for unmodelled casts.
- Explicit stock btree opclass and collation metadata from M2 capture initially caused three FK
  false positives. Real-format corpus cases now distinguish stock metadata from unknown modifiers.
- PostgreSQL folds ASCII in unquoted identifiers while preserving non-ASCII case. Parser, CHECK and
  index matching now use that behavior, verified by offline and live Unicode fixtures.
- Unit and integration tests initially shared `test_classification.py`, causing full-suite import
  collection to fail. The integration file is now `test_m3_corpus.py`; all three server suites and
  the full native suite passed with that name.
- [First branch CI 43741791886](https://github.com/Shellghostt/SchemaSentry/actions/runs/43741791886)
  passed all three PostgreSQL jobs and the dependency audit, but both Python jobs stopped at Ruff
  import ordering. A cached native result had missed the grouping change after new modules were added;
  `ruff check --no-cache .` reproduced it. Test imports were reordered and `schemasentry` declared
  explicitly as first-party for consistent classification, including before new module files exist.
  The README Python example was normalized by the same format contract. Canonical and uncached
  lint/format checks then passed, and all 104 focused M3 tests passed again.

## Reproduction

Use disposable PostgreSQL servers and the synthetic `schemasentry:schemasentry` credentials.
The recorded task-owned servers used ports 55443 (PG13), 55445 (PG15) and 55446 (PG16).
For each server, set its URL and run `make integration`; then run the full suite against PG16:

```powershell
$env:SCHEMASENTRY_TEST_DATABASE_URL='postgresql://schemasentry:schemasentry@127.0.0.1:55446/schemasentry'
$env:PYTEST_ADDOPTS='--cov=src --cov-report=term-missing'
make test
Remove-Item Env:PYTEST_ADDOPTS
make lint
make type
uv build
uvx pip-audit --strict --disable-pip --require-hashes -r requirements.lock
docker build -t schemasentry:m3-test .
.venv/Scripts/python.exe scripts/profile_m3.py --cycles 6 --batches 3
git diff --check
```

## Cleanup

Before shutdown, each server contained zero databases with the `ss_m3_` prefix. Ownership labels,
exact container names, `--rm` and tmpfs data mounts were verified. Only `schemasentry-m3-pg13`,
`schemasentry-m3-pg15` and `schemasentry-m3-pg16` were stopped; all three removed themselves.
No container with `codex.task=schemasentry-m3` remained. Existing Docker projects and volumes were
preserved. The built test image and ignored local artifacts remain available for inspection.
