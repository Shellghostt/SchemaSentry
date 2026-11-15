"""Repeat the synthetic snapshot/diff/parser/classifier lifecycle with tracemalloc and RSS."""

from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import sys
import time
import tracemalloc
from functools import cache
from pathlib import Path
from typing import Any, ClassVar

from schemasentry.classification import classify
from schemasentry.diff import compare, comparison_json, load_snapshot
from schemasentry.hints import RenameHints, load_hints
from schemasentry.migration import parse_migration
from schemasentry.snapshot import Snapshot, to_json

CORPUS = Path(__file__).resolve().parents[1] / "tests" / "corpus"
Case = tuple[Snapshot, Snapshot, str, RenameHints | None]


class _WindowsCounters(ctypes.Structure):
    _fields_: ClassVar[list[tuple[str, Any]]] = [
        ("cb", ctypes.c_uint32),
        ("faults", ctypes.c_uint32),
        ("peak_rss", ctypes.c_size_t),
        ("rss", ctypes.c_size_t),
        ("peak_paged", ctypes.c_size_t),
        ("paged", ctypes.c_size_t),
        ("peak_nonpaged", ctypes.c_size_t),
        ("nonpaged", ctypes.c_size_t),
        ("pagefile", ctypes.c_size_t),
        ("peak_pagefile", ctypes.c_size_t),
        ("private", ctypes.c_size_t),
    ]


@cache
def _windows_api() -> tuple[Any, Any]:
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_WindowsCounters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    return kernel, psapi


def memory() -> dict[str, int | None]:
    if sys.platform == "win32":
        kernel, psapi = _windows_api()
        counters = _WindowsCounters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return {
            "rssBytes": counters.rss,
            "peakRssBytes": counters.peak_rss,
            "privateBytes": counters.private,
        }
    if sys.platform.startswith("linux"):
        import resource

        pages = int(Path("/proc/self/statm").read_text().split()[1])
        return {
            "rssBytes": pages * os.sysconf("SC_PAGE_SIZE"),
            "peakRssBytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        }
    return {"rssBytes": None, "peakRssBytes": None}


def cases() -> tuple[Case, ...]:
    result: list[Case] = []
    for file in sorted(CORPUS.glob("*/expected.json")):
        expected = json.loads(file.read_text(encoding="utf-8"))
        if expected["hintError"]:
            continue
        folder = file.parent
        hint_file = folder / "hints.json"
        result.append(
            (
                load_snapshot(folder / "before.json"),
                load_snapshot(folder / "after.json"),
                (folder / "migration.sql").read_text(encoding="utf-8"),
                load_hints(hint_file) if hint_file.exists() else None,
            )
        )
    return tuple(result)


def batch(inputs: tuple[Case, ...]) -> int:
    findings = 0
    for before, after, source, hints in inputs:
        to_json(before)
        to_json(after)
        comparison_json(compare(before, after))
        result = classify(before, after, migration=parse_migration(source), hints=hints)
        result.model_dump_json()
        findings += len(result.findings)
    return findings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cycles", type=int, default=6)
    parser.add_argument("--batches", type=int, default=3)
    args = parser.parse_args()
    if not 1 <= args.cycles <= 50 or not 1 <= args.batches <= 20:
        parser.error("cycles must be 1-50 and batches 1-20")
    inputs = cases()
    started = time.perf_counter()
    batch(inputs)
    warm_seconds = time.perf_counter() - started
    batch(inputs)
    gc.collect()
    baseline_memory = memory()
    print(
        json.dumps(
            {
                "python": sys.version.split()[0],
                "platform": sys.platform,
                "cases": len(inputs),
                "warmCorpusSeconds": warm_seconds,
                "baseline": baseline_memory,
            }
        ),
        flush=True,
    )
    tracemalloc.start()
    baseline = tracemalloc.take_snapshot()
    samples = []
    for cycle in range(args.cycles):
        tracemalloc.reset_peak()
        started = time.perf_counter()
        count = sum(batch(inputs) for _ in range(args.batches))
        elapsed = time.perf_counter() - started
        gc.collect()
        retained, peak = tracemalloc.get_traced_memory()
        sample = {
            "cycle": cycle + 1,
            "classifications": len(inputs) * args.batches,
            "findings": count,
            "seconds": elapsed,
            "retainedPythonBytes": retained,
            "peakPythonBytes": peak,
            **memory(),
        }
        samples.append(sample)
        print(json.dumps(sample), flush=True)
    final = tracemalloc.take_snapshot()
    growth = [
        {
            "file": str(stat.traceback[0].filename),
            "line": stat.traceback[0].lineno,
            "bytes": stat.size_diff,
            "objects": stat.count_diff,
        }
        for stat in final.compare_to(baseline, "lineno")[:8]
    ]
    tracemalloc.stop()
    print(json.dumps({"samples": samples, "largestRetainedDifferences": growth}), flush=True)


if __name__ == "__main__":
    main()
