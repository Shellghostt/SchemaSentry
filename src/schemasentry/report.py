"""Bounded deterministic JSON and escaped Markdown from the same M4 report."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterable
from itertools import chain

from schemasentry.assessment import Report
from schemasentry.errors import ToolError

MAX_REPORT_BYTES = 16 * 1024 * 1024


def _bounded(chunks: Iterable[str]) -> str:
    collected: list[str] = []
    count = 0
    try:
        for chunk in chunks:
            count += len(chunk.encode("utf-8"))
            if count > MAX_REPORT_BYTES:
                raise ToolError("M4 report exceeds 16 MiB")
            collected.append(chunk)
    except UnicodeError:
        raise ToolError("M4 report contains invalid UTF-8") from None
    return "".join(collected)


def report_json(report: Report) -> str:
    encoder = json.JSONEncoder(ensure_ascii=False, indent=2, allow_nan=False)
    return _bounded(
        chain(encoder.iterencode(report.model_dump(by_alias=True, mode="json")), ("\n",))
    )


def escape_markdown(value: str) -> str:
    visible = "".join(
        f"\\u{ord(character):04x}"
        if ord(character) < 32
        or 127 <= ord(character) < 160
        or unicodedata.category(character) in ("Cf", "Zl", "Zp")
        else character
        for character in value
    )
    punctuation = frozenset("\\`*_{}[]()#+.!|>:-/")
    entities = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#x27;"}
    return "".join(
        entities[character]
        if character in entities
        else "\\" + character
        if character in punctuation
        else character
        for character in visible
    )


def _lines(report: Report) -> Iterable[str]:
    yield "# SchemaSentry assessment\n\n"
    yield (
        f"Report v{report.schema_version}; policy v{report.policy_version}; "
        f"tool {escape_markdown(report.tool_version)}.\n\n"
    )
    yield (
        f"Analysis: **{report.analysis_status}**; "
        f"overall risk: **{report.overall_risk or 'none'}**; "
        f"threshold: **{report.threshold}**.\n\n"
    )
    yield (
        "This is an observed-state assessment, with requested SQL evidence. "
        "It does not predict or apply a migration.\n\n"
    )
    for name, metadata in (("Before", report.before), ("After", report.after)):
        yield (
            f"{name}: snapshot v{metadata.schema_version}, "
            f"catalog evidence {metadata.catalog_evidence_version or 'unavailable'}, "
            f"{escape_markdown(metadata.dialect)} {escape_markdown(metadata.server_version)}, "
            f"capture {escape_markdown(metadata.captured_at)}; digest {metadata.digest}.\n\n"
        )
    if not report.findings:
        yield (
            "No findings were established. This does not mean safe; "
            "check completeness and notices.\n\n"
        )
    for finding in report.findings:
        yield f"## {finding.rule_id}: {escape_markdown(finding.kind)}\n\n"
        yield (
            f"Object: {escape_markdown(finding.schema_name)} / "
            f"{escape_markdown(finding.table or '(enum)')} / "
            f"{escape_markdown(finding.object)}.\n\n"
        )
        yield (
            f"Base severity: **{finding.base_severity}**; "
            f"final risk: **{finding.final_risk}**; confidence: **{finding.confidence}**.\n\n"
        )
        if finding.effects is not None:
            yield (
                f"Effects: lock {finding.effects.lock_level}; scan {finding.effects.scan}; "
                f"rewrite {finding.effects.rewrite}.\n\n"
            )
        else:
            yield "Effects: unavailable.\n\n"
        for evidence in finding.evidence:
            where = (
                f" (line {evidence.location.line}, column {evidence.location.column}, "
                f"chars {evidence.location.start}:{evidence.location.end})"
                if evidence.location
                else ""
            )
            yield f"- Evidence ({evidence.source}){where}: {escape_markdown(evidence.detail)}\n"
        yield "\n"
        for modifier in finding.modifiers:
            yield (
                f"- Modifier {modifier.name}: {modifier.status}, +{modifier.contribution}; "
                f"value {modifier.value if modifier.value is not None else 'unavailable'}. "
                f"{escape_markdown(modifier.evidence)}\n"
            )
        yield "\nEstimated seconds: unavailable.\n\n"
        alternative = (
            escape_markdown(finding.safe_alternative) if finding.safe_alternative else "unavailable"
        )
        yield f"Alternative: {alternative}{'' if finding.safe_alternative else '.'}\n\n"
        for limitation in finding.limitations:
            yield f"- Limitation: {escape_markdown(limitation)}\n"
        yield "\n"
    yield "## Notices and limitations\n\n"
    for notice in report.notices:
        where = (
            f" (line {notice.location.line}, column {notice.location.column})"
            if notice.location
            else ""
        )
        yield (
            f"- {escape_markdown(notice.kind)} [{notice.impact}]{where}: "
            f"{escape_markdown(notice.detail)}\n"
        )
    for limitation in report.limitations:
        yield f"- {escape_markdown(limitation)}\n"


def report_markdown(report: Report) -> str:
    return _bounded(_lines(report)).rstrip("\n") + "\n"
