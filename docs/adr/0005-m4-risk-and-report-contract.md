# ADR 0005 — M4 scoring, report versions and public assessment

- Status: proposed; documentation only
- Date: 2026-11-17
- Required by: [M4 requirements](../phases/M4.md), SS-020A and SS-021–SS-025
- Would extend: ADR 0004 with SS008–SS010 and a public report/scoring wrapper; preserves ADR 0003 diff

## Context

M3 returns immutable internal findings with base severity, confidence, evidence, effects and notices.
It does not aggregate risk or expose new CLI exits. The PLAN scoring sketch combines incompatible max/
additive formulas and duplicates FK exposure. It also suggests seconds from row estimates without a
calibrated rate and a service-reader modifier absent from hints v1. M4 enum checks need label evidence
not present in column type text. Public reports need one complete, deterministic policy and input story.

## Recommended design, pending acceptance

1. Wrap existing findings without mutation. Map low/medium/high/critical to ordinal 0/1/2/3. Add distinct
   known modifier contributions to base rank and clamp at 3. Proposed size contribution is 0 through
   1,000,000 estimated rows, 1 above that through 20,000,000, 2 above 20,000,000. Proposed FK contribution
   is 1 for at least two distinct incoming foreign-key constraints. Do not count one FK twice or add an
   implicit unique-constraint bonus. Overall risk is max(scored findings), absent when there are none.
2. Preserve low confidence/unknown effects and modifier prerequisites explicitly. Unknown inputs do not
   manufacture a modifier or justify a safety claim. The service-reader lock modifier stays unavailable
   under rename-hints v1. `estimatedSeconds` remains null until a separate calibrated model and required
   rewrite/size evidence exist; M4 does not invent a throughput constant.
3. Add report schema v1 separate from snapshot/diff schemas. Propose input/capture versions, analysis
   status, selected threshold, overall risk, scored findings and ordered notices/limitations. Store base
   severity, final risk and each modifier's evidence independently. Both renderers use this model and
   deterministic ordering/UTF-8/LF; no generation clock or secret-bearing connection data enters it.
4. Add `compare --baseline FILE (--after FILE | --database URL)` with optional bounded `--migration FILE`,
   `--hints FILE`, explicit default schema, format and threshold. Preserve `diff` exactly. An after file
   makes the command fully offline even when a database environment variable exists. A live database is
   an observed after state, not a prediction of the supplied migration. Directory parsing remains M5.
5. Propose usage failures as exit 4; invalid/tool/parse/incomplete-required-analysis as exit 3; for complete
   reports, critical risk as 2, otherwise threshold crossed as 1, otherwise 0. Default threshold is high.
   Unsupported evidence produces explicit incomplete results rather than a clean zero-finding success.
   `explain`/`rules` use shared registry metadata and never connect or inspect the machine.
6. SS008/SS009 require typed supported constraint/index operations bound to relevant snapshot objects and
   transaction/version context. SS010 requires explicit enum labels/rename/recreation/dependencies.
   Choose a compatible versioned evidence extension before implementing it; legacy omission is unknown.
   Product paths execute no user migration SQL. Manual alternatives retain PostgreSQL restrictions.

## Choices that must be resolved before acceptance

- Exact modifier composition/deduplication, whether incoming-FK statistics include uncaptured schemas,
  and how incomplete dependency/size metadata is represented. Verify the proposal against reviewed cases.
- Which unsupported/missing signals prevent a complete report, error precedence and report behavior for
  those cases. Preserve the established 0/1/2/3/4 meanings and structural diff's success exit 0.
- Report field names/schema, resource/output bounds, stable report ordering and Markdown escaping.
- Final compare flags/environment precedence and single-file SQL input versus future directory support;
  examples must distinguish an observed after state from migration prediction.
- Enum catalog/evidence representation and version compatibility. Unknown old enum labels cannot be
  assumed removed; a changed column type alone cannot establish membership or data migration.
- Supported SS008/SS009 syntax/versions and truthful alternatives: NOT VALID only for eligible CHECK/FK;
  concurrent indexes cannot run in transaction blocks; enum label removal needs a migration strategy.

## Alternatives considered

- Take max(base rank, modifier number): discards modifiers on high-base findings and differs from the
  additive table. It could be a policy, but must not be mixed with additive bumps accidentally.
- Treat unknown effects as low risk: yields a plausible but unsupported clean assessment.
- Add classification/thresholds to existing diff: breaks consumers of its structural JSON and exit code.
- Predict schema from arbitrary SQL: exceeds the bounded secondary-evidence parser and belongs to a
  separately specified future scope. M4 compares supplied/observed schema states.

## Consequences and validation

The scorer and renderers can be pure and independently tested. Public CLI wiring is explicit in SS-023,
registry commands in SS-024, and SS-020A includes evidence compatibility work. Retain all 59 existing
cases and add at least positive/negative/edge coverage for each new rule rather than merely adding one
case to reach 60. Acceptance also requires deterministic schema/CLI/threshold/incompleteness tests,
read-only live catalog checks and existing resource gates. This record remains proposed.

## PostgreSQL references for the new cases

- [ALTER TABLE and validation](https://www.postgresql.org/docs/16/sql-altertable.html)
- [CREATE INDEX and concurrent-build restrictions](https://www.postgresql.org/docs/16/sql-createindex.html)
- [ALTER TYPE and enum value rename](https://www.postgresql.org/docs/16/sql-altertype.html)
- [Enum implementation and removal limitations](https://www.postgresql.org/docs/16/datatype-enum.html)
