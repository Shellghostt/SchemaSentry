# ADR 0001 - Initial technology and scope decisions

- Status: accepted
- Date: 2026-11-13
- Deciders: Aditya

## Context

SchemaSentry is a greenfield open-source project. Before any code exists, the expensive mistakes to avoid are
scope creep and undocumented stack choices that a future contributor will try to reverse.

## Decisions

1. **Python plus Typer** - the SQL analysis ecosystem is Python-first (sqlglot), CI usage does not need a static binary, and the audience already runs Python in pipelines.
2. **Compare normalised schema state, not SQL text** - text diffs produce false positives on formatting and false negatives on semantic equivalence. The database itself is the reference for "before", the migration is the hypothesis for "after".
3. **SQL parsing is a secondary signal** - parsing is used for lock, rewrite and statement-mix analysis. It never decides breakage on its own.
4. **PostgreSQL first, MySQL later** - one dialect done properly beats two half-done. The dialect layer exists from M1 so MySQL is additive.
5. **The golden corpus is the accuracy contract** - tests/corpus defines correct classification. A rule change that breaks a case is wrong, not "stricter".
6. **Exit codes are public API** - 0 ok, 1 warning threshold, 2 blocking risk, 3 tool error. CI depends on them; changing them is a breaking change.

## Consequences

- The project ships one narrow capability that actually works rather than a broad surface of stubs.
- Contributors have a reference point: changing any decision above requires a superseding ADR, not a
  silent pull request.
- Reversing a decision later is allowed but must be written down with the reason and the migration cost.

## Follow-up

- ADR 0002 is created at M1, recording the concrete schema and interface decisions made while building.
