# Development tools and memory validation

Audit date: 2026-11-14. These are development aids, not product features or substitutes for tests.
Read [PLAN.md](PLAN.md), the [M4 requirements](phases/M4.md), implemented [M3 contract](phases/M3.md)
and accepted [ADRs](adr/) first. M4 ADR 0005 is accepted; [validation](testing/m4-validation.md)
records local M4 checks and pending GitHub CI.

## CodeGraph

CodeGraph 1.6.2 is installed and this repository's existing index was refreshed from merged M2.
The previous index was still at M1. Check freshness when switching branches or pulling changes:

```bash
codegraph status
codegraph sync
```

On 2026-11-17, `codegraph status` reported the existing index up to date against merged M3 source.
No new index or generated source was created for M4 preparation.
The existing index was refreshed again during M4 implementation; no new index or upgrade was performed.

For indexed code, use the CodeGraph MCP exploration tool with this repository's absolute
`projectPath` and the symbol/flow you need. Read its returned source and callers before edits;
use direct source/config searches for areas the graph does not capture. Unresolved references remain,
so the graph does not prove complete dependency coverage, correctness or test coverage.
Builds and CI do not require the local index. Generated databases/transient files stay ignored through
`.codegraph/.gitignore`; do not commit them. Initialize a new index only when intentionally enabling it.

## MemGuard and runtime profiling

MemGuard is JavaScript/TypeScript static resource analysis. It does not analyze Go/Python, inspect a
running process, or prove there are no leaks. Pin its version, check the reported file count and
diagnostics, and inspect resource findings rather than suppressing them to get a green result.

Use Python `tracemalloc` snapshots around repeated snapshot/diff/classification workloads and compare process RSS for native allocations. Force the same workload through several cycles and inspect retained objects after cleanup. Neither MemGuard nor Java HPROF analysis covers this Python project.

For runtime changes, reproduce the suspected workload, record a baseline, repeat the same lifecycle,
then compare live/retained memory after cleanup. Capture allocation rate, heap/RSS, goroutines or
active handles as applicable, and latency/drop metrics. Go benchmarks can collect `-benchmem` and
`-memprofile` for a specific package/workload; inspect profiles with `go tool pprof`. Node supports
heap snapshots/inspector; Python supports `tracemalloc`. Choose the native tool for the process.
Record versions, duration, inputs, commands and limitations in a validation report.
Profile only when the change or suspected fault justifies it; a documentation edit needs link/diff checks.

## M4 implementation validation

`scripts/profile_m4.py` creates one exact owned disposable database, captures 500 populated tables with
enum references and outside-schema incoming FKs, then repeats parser/diff/assessment/JSON/Markdown
lifecycles and over-limit rejection. Its six-cycle run measured 1,194 lifecycles, including the large
snapshot pair, with peak RSS 131,653,632 bytes and post-GC RSS 93,466,624–101,011,456 bytes. Retained traced
Python allocation was 3,484 bytes, dominated by profile samples/bookkeeping. This is finite synthetic
evidence, not a universal leak-free guarantee. Timing and output sizes are in the M4 validation record.

Run `scripts/check_runtime.py` with an installed wheel or in the unprivileged, read-only Docker runtime
with networking disabled. It verifies 59 M3 cases, nine M4 public CLI cases, 30 structural fixtures and
offline metadata commands. Generated rule pages and public schemas are checked with `make check-docs`.
Raw logs/snapshots/profiles stay under ignored `dist/`; runtime dependency versions remain locked.

## Memory Analyzer

The locally installed analyzer is Eclipse MAT 1.17.0, configured with Java 21 and a 4 GiB analyzer heap.
It reads Java/HPROF heap dumps. This repository has no Java runtime workload; MAT is therefore not an
appropriate gate for it. MAT's own heap setting is not this project's memory budget.
Heap dumps/profiles can contain secrets and user data; keep them local/ignored and use synthetic inputs.

## Handoff between editors or assistants

State the branch and commit, read the phase/ADRs, refresh the graph after source changes, and provide
the exact failing command, output and minimal synthetic fixture. Keep implementation on a feature
branch. A skipped integration test must be reported as skipped, with its missing dependency; it is not
a passing check. Preserve local Docker volumes and use disposable databases for migration tests.
