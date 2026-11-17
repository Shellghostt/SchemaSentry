# Development tools and memory validation

Audit date: 2026-11-14. These are development aids, not product features or substitutes for tests.
Read [PLAN.md](PLAN.md), the [M4 requirements](phases/M4.md), implemented [M3 contract](phases/M3.md)
and accepted [ADRs](adr/) first. M4 ADR 0005 remains proposed.

## CodeGraph

CodeGraph 1.6.2 is installed and this repository's existing index was refreshed from merged M2.
The previous index was still at M1. Check freshness when switching branches or pulling changes:

```bash
codegraph status
codegraph sync
```

On 2026-11-17, `codegraph status` reported the existing index up to date against merged M3 source.
No new index or generated source was created for M4 preparation.

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

Use Python tracemalloc/RSS profiles for repeated classification/scoring/JSON/Markdown runs and bounded
input rejection. Retain the 500-table/corpus/memory budgets; include output buffers and parser/rule
evidence, not only an empty renderer. Resource measurements and new public-report cases are future
gates. This pass ran documentation checks only and did not change Python dependencies or catalogs.

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
