# SchemaSentry M4 validation — 2026-11-21

M4 is implemented and locally verified on `feat/m4-implementation`, based on merged M3
`3c76af15670643640cb0efef4d1ab9a49956ca73` and the published preparation `ff41bcf`.
[ADR 0005](../adr/0005-m4-risk-and-report-contract.md) was accepted/committed in `8361dee` before code;
the nine independently reviewed M4 oracles were committed in `31557cc` before dependent rules.
The 59 M3 cases and their expectations are unchanged.

**Final GitHub CI is pending publication. No M4 push, PR, merge or release is claimed here.**
This record covers the local work performed on 2026-11-20–21 and maps the
[M4 requirements](../phases/M4.md) to actual checks.

## Delivered behavior

- SS008 binds eligible named CHECK/FK additions and retained-constraint validation to observed facts.
  Immediate addition and later validation have separate scan/lock semantics; already-valid constraints
  do not establish a new validation scan. NOT VALID retains locks and new-write enforcement.
- SS009 distinguishes ordinary builds, supported concurrent builds and known forbidden transaction/
  partition-parent requests. Forbidden SQL is a requested blocking operation, never a claim it executed.
- SS010 compares known ordered enum membership and supported label requests. Removal is critical;
  supported rename is high. Missing labels remain unknown; PostgreSQL has no direct DROP VALUE.
- Public `compare` uses supplied/observed states and never runs SQL. Both catalog extensions, matching
  scopes and confirmed matching PG13/15/16 semantics are required for complete analysis. Exact supported
  M4 locations have an immutable legacy classification view; other unsupported statements remain visible.
- Risk is `min(3, base rank + size contribution + FK contribution)`. Size boundaries are strict and
  mutually exclusive. Incoming FKs are distinct by source schema/table/name and target the finding's
  table, including outside-schema sources. Optional unknown modifiers never invent a bump or lower
  severity. Reader ownership stays unavailable; `estimatedSeconds` is always null.
- JSON/Markdown use one immutable report and canonical validated evidence. The report includes required
  policy/tool/input/capture versions, digests, effects, modifiers, confidence, alternatives and limitations.
  Markdown escapes hostile markup and makes format/bidi controls visible. Output is bounded and checked;
  atomic publication protects selected inputs and preserves prior destinations on failure.

Default M2 snapshot JSON omits `catalogEvidence`; old serialization/null/order behavior, structural diff
JSON/exits and the default seven-rule M3 classifier/parser remain compatible. M4 additionally rejects
duplicate column positions that would make provenance ordering ambiguous. The optional extension is
explicitly selected with `snapshot --analysis-evidence` and captured automatically by live `compare`.

## Environment and canonical gates

Native Windows amd64, AMD Ryzen 5 5600H (6 cores/12 logical processors), 16,473,133,056 bytes physical RAM.
Python 3.12.10, SQLGlot 30.31.0, Pydantic 2.14.3, psycopg 3.3.9, Typer 0.29.1,
Ruff 0.17.5, mypy 2.4.1 and GNU Make. Runtime dependencies remain unchanged in `requirements.lock`.
The existing virtualenv initially lacked setuptools; its declared build tools were installed as
setuptools 84.2.1/wheel 0.48.0. Updated bootstrap and the Python CI install step include those tools.

| Command/check | Actual result |
|---|---|
| `make test`, PG16 with `PYTEST_ADDOPTS='--cov=src --cov-report=term-missing'` | **405 passed, 8 skipped, 81.66 s; 91% statement coverage** |
| `make integration`, PG13.23 | **84 passed, 8 skipped, 18.19 s** |
| `make integration`, PG15.20 | **84 passed, 8 skipped, 17.05 s** |
| `make integration`, PG16.16 | **84 passed, 8 skipped, 17.15 s** |
| Reviewed M3+M4 unit corpus selection | **68 passed, 2.63 s**, below the 60 s corpus budget |
| `make lint` | Passed: Ruff checks and format check, 165 Python files |
| `make type` | Passed: **38 source files** |
| `make check-docs` | Passed: **13 generated rule-page/schema files** |
| Real `make build` | Built `schemasentry-0.1.0-py3-none-any.whl`; no empty phony target |
| `make audit` | **No known vulnerabilities found**, strict/hash-checked runtime lock |
| `docker build -t schemasentry:m4-test .` | Passed with hashed runtime dependencies |
| Installed Windows wheel, Python 3.12.10 | **59 M3 cases (2 expected hint errors), 9 M4 CLI cases, 30 structural CLI fixtures, 2 metadata commands passed** |
| Unprivileged/read-only Docker runtime, network disabled, Python 3.12.16 | **Same complete installed-runtime checks passed** |
| Owned 500-table capture and lifecycle profile | Passed existing snapshot/diff/corpus/RSS budgets; measurements below |
| Existing CodeGraph refresh and `git diff --check` | Passed; generated index and raw artifacts remain ignored |
| Final GitHub Python 3.12/3.13 and PG13/15/16 CI | **Pending publication; not a passing check yet** |

The 60-second criterion applies to the reviewed corpus, not the complete suite with subprocess/live
integration checks. The final native suite was run alongside separate PG13/15 jobs; measured times
are reported as observed. Coverage is 91% versus the M3 record's 92%: M4 adds defensive/parser branches,
and real CLI subprocess coverage is not aggregated into the parent report. Functional subprocess tests
pass; some fallback paths remain uncovered. This reduction is disclosed rather than padded with tests.
Setuptools also emits the existing TOML license-table deprecation warning; the build succeeds.

## Acceptance mapping

| Requirement | Tests/evidence |
|---|---|
| Reviewed positive/negative/edge cases for SS008–SS010; preserve all 59 M3 oracles | `test_reviewed_m4_corpus`, `test_m4_corpus_floor_and_new_rule_coverage`, `test_reviewed_m3_corpus`; 59+9=68 |
| Validation stages, locks and uncertainty | `test_existing_not_valid_check_validation_has_its_own_scan_and_lock`, `test_added_not_valid_then_validation_preserves_both_requested_stages`, `test_validation_transition_without_sql_retains_uncertainty`, `test_live_existing_constraint_validation_scan_and_lock` |
| Index/enum restrictions and missing/version evidence | `test_live_index_build_mode`, `test_live_concurrent_index_transaction_and_partition_restrictions`, `test_each_new_rule_retains_missing_catalog_evidence`, `test_unconfirmed_versions_never_establish_new_rule_effects`, `test_direct_enum_drop_value_syntax_remains_unsupported` |
| Contradictory/unresolved SQL and mixed M3/M4 evidence | `test_constraint_sql_without_observed_object_is_incomplete`, `test_enum_sql_cannot_establish_unobserved_membership_changes`, `test_supported_m4_statements_do_not_poison_legacy_lock_evidence`, `test_rollback_of_legacy_operation_is_incomplete_in_public_assessment` |
| Exact modifier boundaries, cap, confidence and aggregate/exit precedence | `test_exact_size_tiers`, `test_distinct_incoming_fk_boundary`, `test_known_modifiers_add_once_and_cap_with_confidence_retained`, `test_unknown_modifiers_are_explicit_and_do_not_lower_base`, `test_incomplete_precedes_critical_and_threshold_never_suppresses_critical` |
| Null duration, separate uncertainty and schema completeness | `test_public_report_matches_schema_and_only_estimated_seconds_null`, `test_report_schema_requires_policy_provenance_and_nullable_uncertainty_fields`, all M4 corpus/runtime checks assert null seconds |
| Stable JSON/Markdown and hostile input goldens | `test_repeated_and_shuffled_inputs_preserve_report_bytes_and_diff`, `test_shuffled_catalog_reference_facts_preserve_report_bytes`, `test_markdown_matches_reviewed_complete_and_hostile_goldens`, `test_all_bidi_and_invisible_format_controls_are_visible_in_markdown` |
| Real CLI thresholds and exits 0/1/2/3/4, offline/environment/output policy | `test_complete_high_risk_thresholds_use_real_cli`, `test_critical_always_returns_two_and_incomplete_three`, `test_no_findings_offline_and_invalid_usage_codes`, `test_metadata_commands_are_offline_with_database_environment`, `test_successful_file_output_has_no_stdout_and_closed_stdout_is_tool_error` |
| Actual observed live state; no execution or connection-info leakage | `test_live_compare_observes_baseline_scope_and_never_executes_migration`; the requested drop leaves the actual column/data intact and returns incomplete 3 |
| Strict catalog versions/duplicates/consistency, legacy unknown and read-only capture | `test_catalog_version_is_strict_and_explicit`, `test_duplicate_catalog_facts_are_rejected`, `test_inconsistent_scope_relations_and_constraint_validity_are_rejected`, `test_enum_reference_cannot_point_at_an_integer_column`, `test_incoming_fk_matches_scoped_source_and_cannot_omit_it`, `test_m4_capture_keeps_read_only_repeatable_read_and_statement_timeout` |
| Enum arrays, outside scope, unsupported wrappers and known empty enums | `test_live_enum_labels_rename_arrays_and_domain_uncertainty`, `test_live_uncaptured_type_dependencies_remain_incomplete`, `test_live_known_empty_enum_is_not_legacy_unknown` on all three servers |
| Resource bounds and checked atomic output | `test_dynamic_input_string_at_and_over_utf8_bound`, `test_combined_object_bound_is_checked_before_classification`, `test_finding_and_notice_bounds_fail_without_truncating`, `test_actual_report_byte_bound_counts_encoded_utf8_and_keeps_last_byte`, `test_both_renderers_enforce_the_entire_document_boundary`, `test_catalog_queries_share_remaining_budget_and_request_one_over_limit` |
| Input alias/symlink/hardlink and output failures | `test_hardlink_output_alias_cannot_overwrite_selected_input`, `test_symlink_report_destination_is_rejected`, `test_atomic_failure_preserves_destination_and_removes_owned_stage`, `test_fsync_failure_preserves_previous_report`, `test_short_writer_is_an_error`, `test_flush_failure_is_a_complete_output_error` |
| Public registry-derived documentation and packaging | `test_public_documentation_and_schemas_have_no_generated_drift`, `make check-docs`, real wheel build and `scripts/check_runtime.py` installed-runtime checks |

## Live matrix and skips

All three disposable services belong to Compose project `ss-m4-20261120`:
PG13 at 55453, PG15 at 55455 and PG16 at 55456. Each M3/M4 catalog fixture creates and drops its exact
owned `ss_m3_<uuid>`/`ss_m4_<uuid>` database; the older snapshot fixture owns an `ss_it_<uuid>` schema.
Only generated/committed synthetic test SQL is applied. Product capture remains read-only.

All 16 new live M4 cases pass on PG13.23/15.20/16.16. The same eight M3 cases remain intentionally offline:
0014 untested version, 0015 contradictory typmods, 0021 missing legacy CHECK definition, 0027 invalid index,
0031 missing legacy keys, 0032 custom opclass, 0052 unproven assignment cast, 0055 SQL/snapshot type mismatch.
They all pass offline; no new integration case was skipped to conceal a differing result.
PG13 is compatibility evidence, not a deployment recommendation. Capture still accepts 13–17;
confirmed classification effects remain limited to matching tested 13/15/16 semantics.

## 500-table and lifecycle measurements

Command: `.venv/Scripts/python.exe scripts/profile_m4.py --cycles 6 --batches 3`, against the owned PG16.
The profiler creates one fresh `ss_m4_perf_<uuid>` database, 500 tables with 100 rows/four initial columns
each, enum column references and two incoming FKs from an outside-schema source. Sixty-one generated
changes produce 81 findings (including 20 legacy lock findings). The profiler drops its exact database
in `finally`; raw snapshots/reports stay in ignored `dist/m4-profile/`.

| Measurement | Result |
|---|---|
| Before / after read-only capture | 0.503396 / 0.465221 s; each below 5 s |
| Before / after snapshot encoding | 0.063222 / 0.064791 s |
| Snapshot sizes | 1,184,628 / 1,194,391 UTF-8 bytes |
| Structural diff + JSON | 0.073839 s; below 10 s |
| Parse + complete M4 assessment | 0.465828 s |
| JSON / Markdown encoding | 0.010875 / 0.031523 s |
| JSON / Markdown report sizes | 187,772 / 150,115 bytes |
| Warmed 66-case valid-input profile batch | 0.183371 s; two expected hint-error cases are separately covered by tests |
| Repeated lifecycles | 6 × (66 × 3 + 1 large pair) = **1,194**, plus warmups and repeated over-limit rejection |
| Per-cycle traced duration | 4.509–5.176 s |
| Process peak RSS | **131,653,632 bytes**, below 300,000,000 |
| Post-GC RSS across cycles | 93,466,624–101,011,456 bytes |
| Peak traced Python allocation / final retained | 12,603,158 / 3,484 bytes |

Largest retained differences belong to profiler samples, tracemalloc bookkeeping and memory-counter
records. No persistent product allocation growth was apparent in this finite run. Native allocator RSS
varies; this does not establish absence of leaks for arbitrary schemas or unbounded lifetimes. MemGuard
and Java heap tools were not used as Python gates.

## Corrections verified during implementation

The expanded checks caught retained NOT VALID validation being missed, unmatched requested constraint/
enum operations being treated as complete, and domain/composite arrays missing their dependency gaps.
Those production paths now have explicit regression/live coverage. Mixed supported M3/M4 SQL initially
lost legacy lock confidence; the immutable classification view corrects only recognized locations while
retaining unknown statements. Canonicalizing evidence also fixed shuffled enum-reference text changing
report bytes. Closed stdout no longer changes tool exit 3 to Python shutdown exit 120. These fixes do
not rewrite any committed corpus expectation or alter the default M3 entry point.

The first large profiler assertion also undercounted the expected findings (61 operations produce 81
findings because column drops have separate lock findings), and one test wrongly expected no findings
when a retained FK still lacked supporting index coverage. Those expectations were corrected as test/
instrumentation errors; existing M3 behavior was preserved.

## Reproduction

Install the hashed runtime lock before development tools. Use fresh disposable PG13/15/16 servers with
the synthetic `schemasentry:schemasentry` credentials and CREATE DATABASE privilege, then run each matrix:

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e '.[dev]' 'setuptools>=75' wheel
$env:SCHEMASENTRY_TEST_DATABASE_URL='postgresql://schemasentry:schemasentry@127.0.0.1:55456/schemasentry'
make integration
$env:PYTEST_ADDOPTS='--cov=src --cov-report=term-missing'
make test
Remove-Item Env:PYTEST_ADDOPTS
make lint
make type
make check-docs
make build
make audit
.\.venv\Scripts\python.exe scripts/profile_m4.py --cycles 6 --batches 3
docker build -t schemasentry:m4-test .
docker run --rm --network none --read-only --env PYTHONDONTWRITEBYTECODE=1 `
  --mount "type=bind,source=$($PWD.Path)\tests,target=/fixtures,readonly" `
  --mount "type=bind,source=$($PWD.Path)\scripts\check_runtime.py,target=/check_runtime.py,readonly" `
  --entrypoint python schemasentry:m4-test /check_runtime.py --fixtures /fixtures
git diff --check
```

For the native installed check, create a separate virtualenv under ignored `dist/`, install
`requirements.lock` with `--require-hashes`, install the wheel with `--no-deps`, and run
`scripts/check_runtime.py --fixtures tests` with that environment's interpreter. The measured environment
was `dist/m4-installed-20261121`; its imported package path was inside its `Lib/site-packages`.

## Cleanup and publication

Each disposable server had zero owned `ss_m3_`/`ss_m4_` databases and `ss_it_` schemas after validation.
The three task-owned services were stopped with
`docker compose -p ss-m4-20261120 -f dist/m4-pg.compose.json down` without volume deletion.
Existing Docker projects/data are preserved. Logs, wheel, runtime image and raw profiles
remain local for review. Final GitHub CI requires authorized feature-branch publication; merge remains
a separate decision.
