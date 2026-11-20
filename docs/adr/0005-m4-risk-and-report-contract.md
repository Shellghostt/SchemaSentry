# ADR 0005 — M4 scoring, report versions and public assessment

- Status: accepted for `feat/m4-implementation`
- Proposed: 2026-11-17; accepted: 2026-11-20
- Required by: [M4 requirements](../phases/M4.md), SS-020A and SS-021–SS-025
- Would extend: ADR 0004 with SS008–SS010 and a public report/scoring wrapper; preserves ADR 0003 diff

## Context

M3 returns immutable internal findings with base severity, confidence, evidence, effects and notices.
It does not aggregate risk or expose new CLI exits. The PLAN scoring sketch combines incompatible max/
additive formulas and duplicates FK exposure. It also suggests seconds from row estimates without a
calibrated rate and a service-reader modifier absent from hints v1. M4 enum checks need label evidence
not present in column type text. Public reports need one complete, deterministic policy and input story.

## Decision

1. Wrap existing findings without mutation. Map low/medium/high/critical to ordinal 0/1/2/3. Add distinct
   known modifier contributions to base rank and clamp at 3. Size contribution is 0 through
   1,000,000 estimated rows, 1 above that through 20,000,000, 2 above 20,000,000. FK contribution
   is 1 for at least two distinct incoming foreign-key constraints. Do not count one FK twice or add an
   implicit unique-constraint bonus. Overall risk is max(scored findings), absent when there are none.
2. Preserve low confidence/unknown effects and modifier prerequisites explicitly. Unknown inputs do not
   manufacture a modifier or justify a safety claim. The service-reader lock modifier stays unavailable
   under rename-hints v1. `estimatedSeconds` remains null until a separate calibrated model and required
   rewrite/size evidence exist; M4 does not invent a throughput constant.
3. Add report schema v1 separate from snapshot/diff schemas. Include input/capture versions, analysis
   status, selected threshold, overall risk, scored findings and ordered notices/limitations. Store base
   severity, final risk and each modifier's evidence independently. Both renderers use this model and
   deterministic ordering/UTF-8/LF; no generation clock or secret-bearing connection data enters it.
4. Add `compare --baseline FILE (--after FILE | --database URL)` with optional bounded `--migration FILE`,
   `--hints FILE`, explicit default schema, format and threshold. Preserve `diff` exactly. An after file
   makes the command fully offline even when a database environment variable exists. A live database is
   an observed after state, not a prediction of the supplied migration. Directory parsing remains M5.
5. Usage failures return exit 4; invalid/tool/parse/incomplete-required-analysis return exit 3; for complete
   reports, critical risk as 2, otherwise threshold crossed as 1, otherwise 0. Default threshold is high.
   Unsupported evidence produces explicit incomplete results rather than a clean zero-finding success.
   `explain`/`rules` use shared registry metadata and never connect or inspect the machine.
6. SS008/SS009 require typed supported constraint/index operations bound to relevant snapshot objects and
   transaction/version context. SS010 requires explicit enum labels/rename/recreation/dependencies.
   Choose a compatible versioned evidence extension before implementing it; legacy omission is unknown.
   Product paths execute no user migration SQL. Manual alternatives retain PostgreSQL restrictions.

## Compatible catalog evidence

Snapshot schema v1 gains optional `catalogEvidence` with its own `evidenceVersion: 1`. Omission or null
means unknown evidence, including unknown enum membership. Serialization omits this new field when
absent; all old snapshot fields/nulls/order, structural `diff` bytes/exits and the M3 seven-rule
`classify` entry point remain compatible. M4 assessment and the public registry use all ten rules.

`snapshot --analysis-evidence` explicitly captures this extension. Its default output remains the
existing snapshot. Live `compare` captures the extension in the same read-only REPEATABLE READ
transaction and retains the five-second statement timeout. It executes no supplied migration.

The extension has the captured schema scope, ordinary/partitioned relation facts, named CHECK/FK
validation facts, enum names and ordered labels, captured column references to enums, and complete
incoming foreign-key facts for captured target tables. Incoming facts include referencing tables
outside the selected schemas. Distinctness is `(source schema, source table, constraint name)`;
only constraints targeting the finding's table count, with no extra UNIQUE bonus. Legacy omission
produces an unknown FK modifier rather than a zero exposure assertion.

Enum scope is the selected schemas. References from selected columns to enum types outside that scope,
and unsupported domain wrappers, are explicit gaps. Captured dependencies cover selected columns;
uncaptured application/other-schema dependencies remain limitations. Enum identity uses qualified names,
not database-local OIDs. Labels preserve catalog order; a known empty enum differs from missing evidence.
Extension validation rejects duplicate/inconsistent scope, relation, enum, reference and constraint facts.

## Completeness, scoring and report bounds

Final risk is `min(3, base rank + size contribution + FK contribution)`. The two size tiers are mutually
exclusive. Each modifier is applied once, records its prerequisite/evidence and remains distinct from
confidence. Unknown size/FK facts contribute no invented bump; an unavailable reader-ownership modifier
is disclosed. These optional modifier gaps and absent calibrated seconds do not invalidate otherwise
complete classification. Overall risk is the maximum final risk, or null for no findings.

A complete assessment requires both catalog extensions, matching snapshot schema scope and confirmed
matching PostgreSQL 13/15/16 semantics. Missing required enum/constraint/index evidence, low-confidence
target classification, unresolved targets, parser errors, unsupported target statements, inconsistent
evidence and unbalanced transaction wrappers yield `analysisStatus: incomplete`. Missing optional SQL
is informational for wholly snapshot-established risks; operations whose semantics require SQL remain
incomplete without it. A supported new M4 statement supersedes only the M3 unsupported notice for that
exact source location. Other M3 notices and findings retain their meaning.

Exit precedence is usage 4; invalid input/tool/output failure or incomplete assessment 3; then complete
critical risk 2 regardless of threshold; complete threshold crossing 1; otherwise 0. Zero findings or
exit 0 establishes no general safety claim. A known invalid concurrent-index transaction is reported
as blocking requested SQL, never as an operation proven to have executed.

Report v1 contains `schemaVersion`, `policyVersion`, `toolVersion`, `analysisStatus`, `threshold`,
`overallRisk`, before/after input digests and capture-version metadata, immutable scored findings,
ordered notices and limitations. Findings retain schema/table/object/kind, base severity, final risk,
confidence, effects, evidence/source locations, modifiers and nullable alternatives/`estimatedSeconds`.
No configured DSN, report-generation timestamp or random ID enters the model. Input digests cover
canonical validated snapshots. `estimatedSeconds` remains null throughout M4.

Existing input byte/parser limits remain. M4 additionally caps combined structural/catalog objects
at 200,000, findings at 10,000, notices at 2,048, each dynamic input string at 256 KiB, and either encoded
report at 16 MiB. Catalog queries use explicit row bounds before materializing additional evidence.
Limit failures are explicit, without truncating findings or reporting a partial success. Renderers
complete their bounded UTF-8/LF buffer before output; short writes/flush failures return 3. Atomic file
output preserves the prior destination on failure and cannot overwrite a selected input.

JSON ordering is stable. Markdown uses repository-owned structure and escapes dynamic markup, links,
HTML, pipes, fences and visible terminal/bidi controls. Repeated/shuffled validated inputs and the same
policy yield identical bytes. Captured timestamps are input provenance, not a generation clock.

## Public commands

- `compare --baseline FILE` selects `--after FILE` or explicit `--database URL`. When after is present,
  a database environment variable is ignored and no connection occurs. Explicit after plus explicit
  database is usage 4. With neither explicit choice, `SCHEMASENTRY_DATABASE_URL` supplies the live URL;
  an absent URL is usage 4. Live capture uses the baseline's declared schema scope.
- Optional `--migration FILE` and `--hints FILE` retain the existing single-file bounds.
  `--default-schema` defaults to `public` and binds unqualified SQL identifiers explicitly.
  `--format markdown|json` defaults to Markdown; `--threshold low|medium|high|critical` defaults to high.
  `--output FILE` selects atomic file publication. `--captured-at` applies only to live capture.
  Invalid combinations/policy values fail before file reads or connection attempts.
- `explain RULE` and `rules [--json]` use immutable ten-rule metadata, including fixed PostgreSQL
  references and caveats, with no capture, database lookup or machine inspection.
- M4 `compare` compares supplied/observed before and after states. Migration SQL is bounded secondary
  evidence; no command predicts its future schema, traverses migration directories or applies SQL.

## New rule semantics

- SS008 identifies supported added named CHECK/FK constraints and validation requests. Ordinary CHECK
  addition takes ACCESS EXCLUSIVE; ordinary FK addition takes SHARE ROW EXCLUSIVE on relevant tables.
  Immediate validation requires scanning existing rows. `NOT VALID` avoids that initial validation
  scan but retains locks/new-write enforcement; later validation has its own locks. It is not advice
  for UNIQUE, PRIMARY KEY or NOT NULL. Missing validation/target facts remain incomplete.
- SS009 binds supported CREATE INDEX evidence to the relevant table/index and reports ordinary-build
  write blocking. `CONCURRENTLY` has multiple phases, can leave invalid indexes and cannot run inside
  explicit transactions. A partitioned parent cannot be built concurrently directly; leaf/attach
  guidance stays conditional. Unknown concurrency, partition or expression binding is explicit.
- SS010 compares known enum membership and supported rename/recreation evidence. Added labels alone
  are not label removal. Rename preserves order but can affect readers. Removed labels/types have
  critical policy risk and conditional rebuild/data-mapping advice; PostgreSQL has no direct DROP VALUE.
  Column type text alone never establishes enum labels or proves a data migration.

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
cases unchanged and add a separate M4 corpus with positive/negative/edge coverage for each new rule,
with reviewed expectations committed before dependent rule code, rather than merely adding one
case to reach 60. Acceptance also requires deterministic schema/CLI/threshold/incompleteness tests,
read-only live catalog checks and existing resource gates. Acceptance results remain separate evidence.

## PostgreSQL references for the new cases

- [ALTER TABLE and validation](https://www.postgresql.org/docs/16/sql-altertable.html)
- [CREATE INDEX and concurrent-build restrictions](https://www.postgresql.org/docs/16/sql-createindex.html)
- [ALTER TYPE and enum value rename](https://www.postgresql.org/docs/16/sql-altertype.html)
- [Enum implementation and removal limitations](https://www.postgresql.org/docs/16/datatype-enum.html)
