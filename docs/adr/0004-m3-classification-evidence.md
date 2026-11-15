# ADR 0004 — M3 classification, rename hints and bounded SQL evidence

- Status: accepted for the M3 feature branch
- Date: 2026-11-15
- Supersedes: ADR 0002 decision 11 only for the scheduling of minimal SQL parsing and the initial hint format
- Preserves: ADR 0003 structural diff/wire/exit contracts and M1 read-only capture

## Decisions

1. M3 adds a library classification API and a registry for SS001–SS007. It consumes immutable snapshot
   data, optional parsed migration evidence, and optional validated column rename hints. It returns
   deterministic findings and explicit evidence notices. Findings carry separate schema/table/object
   identity, rule ID, change kind, base severity, confidence, evidence, limitations and a manual
   alternative where available. There is no aggregate risk, size modifier, duration, public report,
   threshold, `compare`, `explain` or new CLI exit behavior in M3. Those remain M4.
2. Existing snapshot models, capture SQL, structural comparison and CLI remain unchanged. Classification
   calls the existing comparator but does not modify its inputs or response. Physical order/statistics,
   sequences/extensions and uncaptured table properties do not silently become structural comparisons.
   Findings distinguish observed state from declared migration operations; a parsed file is not proof
   that SQL was executed. Missing migration input and unsupported evidence are visible notices.
3. Minimal SQL parsing uses the locked SQLGlot 30.31 series with PostgreSQL syntax. Files are UTF-8 data,
   bounded to 256 KiB, 128 statements, 20,000 tokens and 64 levels of delimiter nesting. Statement
   order, original bounded text, character offsets and one-based line/column are retained. Each result
   is supported, unsupported or a parse error. Recognized operations include ordinary ALTER TABLE
   column type/nullability/default/add/drop/rename operations, transaction wrappers, and targeted
   VACUUM FULL. Generated/identity columns, arbitrary commands, unsupported ALTER actions and broader
   migration prediction remain explicit unsupported results. An unsupported action cannot turn the
   whole statement into a silently supported one. SQLGlot fallback warnings are suppressed locally
   in this parser instance; unknown syntax is returned as data, never echoed to logs or executed.
4. Schema-qualified identifiers retain PostgreSQL quoting/case semantics. Unqualified operation targets
   need an explicitly supplied default schema to bind to snapshots; capture scope is not a search-path
   substitute. Unsupported statements, mismatched targets/types and unknown or differing server versions
   prevent unsupported operation effects from being asserted. M3's confirmed version-specific effects
   are limited to the PG 13/15/16 regression matrix. Introspection still accepts majors 13–17 under its
   existing contract; classification on other/unrecognized versions keeps effects uncertain.
5. Rename hints are strict JSON v1, not executable configuration. The initial file is at most 64 KiB
   with at most 128 mappings:

   ```json
   {"schemaVersion":1,"renames":[{"schema":"public","table":"users","from":"old","to":"new"}]}
   ```

   Unknown/duplicate fields, noninteger versions, duplicate endpoints, collisions, cycles, absent
   endpoints or a mapping that is not an actual drop/add in that table are errors. Matching is one-to-one
   and independent of input ordering. A validated hint pairs columns only inside classification:
   SS001 is suppressed for that pair, SS006 records the declaration, and type/nullability/default
   differences on the paired columns are still classified. No hint proves preservation of data or
   reader compatibility. Without hints the existing drop/add evidence remains. Table renames are not
   inferred. PyYAML remains declared but unused by this initial strict JSON contract.
6. SS001 classifies removed columns, including columns recorded inside a removed table. Its critical
   base severity is a compatibility policy: readers that still reference them can break. It does not
   claim every application reads them. A removed table is not expanded in structural diff; this is
   classification of the column evidence already present in that change.
7. SS002 preserves the documented type matrix. Varchar capacity widening is distinct from narrowing;
   integer-to-bigint is medium, bigint-to-integer is high, text-to-bounded-varchar and timestamp-to-
   timestamptz are high, and numeric widening is medium. Unknown/domain types, inconsistent typmods,
   unsupported versions and unmodelled USING conversions are not inferred harmless. An explicit
   unmodelled USING conversion prevents a widening case from being treated as a negative finding.
   Type policy and actual scan/rewrite evidence are separate: confirmed effects require a matching,
   single supported operation and known server semantics. Numeric and timezone conversion effects
   remain conditional/unknown; no durations are estimated.
8. SS003 never uses an ordinary default as proof that historical rows are nonnull. An exact CHECK
   definition from the existing pg_get_constraintdef evidence can establish a local-column proof
   when it entails `column IS NOT NULL` and is validated: NOT VALID, missing definitions, OR expressions
   and NO INHERIT are not accepted proof. Matching proof must remain present across the snapshots;
   unsupported intervening operations prevent scan-avoidance assertions. PG 13/15/16 can use such
   validated CHECK evidence to avoid the NOT NULL scan, but SET NOT NULL still acquires its DDL lock.
   Inheritance/partition scope is not captured, so effects are conditional on the represented table.
9. SS004 examines the referencing side of each foreign key in the after snapshot. Proven coverage
   requires a valid btree index with complete key metadata, no partial predicate, and all FK columns
   as the leading plain key columns. Equality keys may appear in a different order. Included columns
   do not count; expressions before the required prefix cannot establish coverage, while expressions
   after a complete prefix do not invalidate it. Custom collation/opclass, partial predicates and
   legacy/missing keys stay unproven rather than being described as definitely absent. Findings use
   lower confidence for potentially usable but unsupported evidence. Size scaling belongs to M4.
10. SS005 records parsed lock/scan/rewrite evidence separately. Supported ordinary ALTER TABLE column
    operations use ACCESS EXCLUSIVE; SET/DROP DEFAULT changes future defaults without rewriting old
    rows; targeted VACUUM FULL rewrites and uses ACCESS EXCLUSIVE. ADD COLUMN defaults can use PG11+
    fast-default behavior only with known nonvolatile ordinary-column/type evidence. Unknown function
    resolution, casts, generated columns, multiple interacting operations and unsupported SQL do not
    authorize a rewrite/no-rewrite assertion. Snapshot differences alone never identify the operation.
11. SS007 distinguishes literals/known nonvolatile SQL constructs, explicit known pg_catalog volatile
    functions and unknown function resolution. CURRENT_TIMESTAMP and nonliteral expressions are not
    automatically volatile. User functions and unqualified function names stay unknown without catalog
    resolution evidence. A small documented catalog-function allowlist does not stand for every function.
    SET DEFAULT affects future writes; a volatile ADD COLUMN default can rewrite on the tested versions.
    Unknown volatility is a medium, low-confidence finding with explicit limitations, not a volatile claim.
12. Reviewed corpus expectations precede rule implementation. Every rule has positive/negative/edge
    cases plus ambiguity cases. Offline fixtures pin schema states and parser input; live corpus tests
    apply only committed synthetic SQL inside the task's disposable PostgreSQL test databases. Product
    paths never execute migration input. Tests cover frozen-input/determinism, bounds, malformed hints,
    SQL nonexecution, existing 30 structural pairs/CLI exits and read-only PG 13/15/16 capture. The corpus
    must finish under 60 seconds. Python tracemalloc/RSS evidence accompanies the new workload; MemGuard
    and Java heap tools do not prove Python resource behavior.

## References

- PostgreSQL 13/15/16 ALTER TABLE: <https://www.postgresql.org/docs/16/sql-altertable.html> (lock defaults,
  validated CHECK/NOT NULL scans, default and type-change behavior).
- Fast defaults and volatility: <https://www.postgresql.org/docs/16/ddl-alter.html> and
  <https://www.postgresql.org/docs/16/xfunc-volatility.html>.
- Foreign-key indexes: <https://www.postgresql.org/docs/16/ddl-constraints.html#DDL-CONSTRAINTS-FK> and
  <https://www.postgresql.org/docs/16/indexes-multicolumn.html>.
- VACUUM FULL: <https://www.postgresql.org/docs/16/sql-vacuum.html>.
- Constraint rendering/validation: <https://www.postgresql.org/docs/16/functions-info.html> and
  <https://www.postgresql.org/docs/16/catalog-pg-constraint.html>.

## Consequences

M3 adds internal evidence-based classification without changing M2 behavior or making M4 risk claims.
Unknown evidence remains visible, and confirmed effects have narrow version/syntax prerequisites.
The fixture corpus, live regression matrix and canonical test/lint/type gates must pass before status
documents claim implementation or completion. CI must actually run before its checkbox is ticked.
