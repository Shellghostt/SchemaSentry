"""Offline public ten-rule metadata and registry-derived documentation."""

from schemasentry.evidence import RuleMetadata
from schemasentry.m4_rules import public_rule_metadata


class PublicRule(RuleMetadata):
    evidence_requirements: tuple[str, ...]
    references: tuple[str, ...]
    limitations: tuple[str, ...]


def public_rules() -> tuple[PublicRule, ...]:
    references = {
        "SS001": ("sql-altertable.html",),
        "SS002": ("sql-altertable.html",),
        "SS003": ("sql-altertable.html",),
        "SS004": ("ddl-constraints.html",),
        "SS005": ("sql-vacuum.html", "sql-altertable.html"),
        "SS006": ("sql-altertable.html",),
        "SS007": ("xfunc-volatility.html",),
        "SS008": ("sql-altertable.html", "explicit-locking.html"),
        "SS009": ("sql-createindex.html",),
        "SS010": ("datatype-enum.html", "sql-altertype.html"),
    }
    evidence = {
        "SS001": (
            (
                "A column is present before and absent after, including removal of "
                "its containing table."
            ),
            "A strict, validated rename hint can establish paired endpoints instead of removal.",
        ),
        "SS002": (
            "Both observed column types and typmods bind to the reviewed PostgreSQL type matrix.",
            "Requested ALTER TYPE evidence must match the column and explicitly selected schema.",
        ),
        "SS003": (
            "Observed nullability changes or a newly added NOT NULL column are explicit.",
            "Historical nonnull proof requires the narrow retained, validated CHECK evidence.",
        ),
        "SS004": (
            "The referencing FK columns and their types are captured.",
            "Coverage needs valid, complete leading btree equality keys with known decorations.",
        ),
        "SS005": (
            "A supported VACUUM FULL statement is bound to a captured table.",
            "Requested operation evidence establishes a lock request, not executed SQL.",
        ),
        "SS006": (
            "Strict rename-hints v1 pairs existing source and target columns without collisions.",
            "SQL spelling alone does not create a rename hint.",
        ),
        "SS007": (
            (
                "Observed/declared defaults and bound operations use the reviewed "
                "volatility allowlist."
            ),
            "User functions, unqualified function resolution and unknown casts stay uncertain.",
        ),
        "SS008": (
            (
                "Named CHECK/FK definitions, captured validation facts and supported "
                "requested SQL agree."
            ),
            "Immediate addition and later validation have distinct scan/lock stages.",
            (
                "Confirmed constraint effects require a supported ordinary relation; "
                "partition/inheritance variants remain uncertain."
            ),
            "Revalidating a retained already-valid constraint does not establish a new scan.",
        ),
        "SS009": (
            "Index name, ordinary relation kind, simple columns and observed index metadata agree.",
            "Concurrent requests retain explicit transaction context and partition-parent facts.",
        ),
        "SS010": (
            "Both versioned catalogs contain known ordered enum labels; omission is unknown.",
            (
                "Supported rename/recreation requests bind to observed membership and"
                " column references."
            ),
        ),
    }
    caveats = {
        "SS001": ("Reader usage and data-preservation intent are not captured by snapshots.",),
        "SS002": (
            "USING, unreviewed casts, generated columns and inconsistent typmods stay uncertain.",
        ),
        "SS003": (
            (
                "A default does not prove historical values were backfilled or "
                "pre-existing NULLs removed."
            ),
        ),
        "SS004": (
            (
                "UNIQUE constraints add no implicit FK-exposure bonus; included "
                "columns are not equality keys."
            ),
        ),
        "SS005": ("VACUUM FULL rewrites the table; ordinary VACUUM is a different operation.",),
        "SS006": ("Hints do not describe service-reader ownership or authorize a data migration.",),
        "SS007": (
            (
                "Nonliteral does not mean volatile; SET DEFAULT does not itself "
                "rewrite historical rows."
            ),
        ),
        "SS008": (
            "NOT VALID is eligible for CHECK/FK, not UNIQUE, PRIMARY KEY or NOT NULL.",
            (
                "NOT VALID retains addition locks and new-write enforcement; "
                "validation can fail on existing rows."
            ),
            (
                "FK validation also acquires ROW SHARE on the referenced relation; "
                "the finding lock describes the source table."
            ),
        ),
        "SS009": (
            (
                "CONCURRENTLY cannot run in an explicit transaction or directly on a "
                "partitioned parent."
            ),
            (
                "Concurrent builds have multiple phases, lock waits and possible "
                "invalid-index cleanup."
            ),
            (
                "Expression, opclass, storage and conditional variants outside the "
                "supported binding are incomplete."
            ),
        ),
        "SS010": (
            (
                "Added labels alone are not removal; a supported label rename has "
                "high base policy risk."
            ),
            (
                "PostgreSQL has no direct DROP VALUE; rebuild/data mapping remains a "
                "conditional manual plan."
            ),
            (
                "Domain/composite wrappers and references outside captured scope are "
                "explicit dependency gaps."
            ),
            (
                "Captured columns do not describe all application string consumers or"
                " uncaptured schemas."
            ),
        ),
    }
    return tuple(
        PublicRule(
            **metadata.model_dump(by_alias=True),
            evidence_requirements=evidence[metadata.rule_id],
            references=tuple(
                "https://www.postgresql.org/docs/16/" + reference
                for reference in references[metadata.rule_id]
            ),
            limitations=(
                *caveats[metadata.rule_id],
                (
                    "Registry severity is the rule default; condition-specific "
                    "findings can use another base severity."
                ),
                "Policy severity and confidence are distinct; unknown evidence is explicit.",
                "Confirmed operation effects require matching PostgreSQL 13/15/16 evidence.",
                "No calibrated duration or general safety guarantee is available.",
            ),
        )
        for metadata in public_rule_metadata()
    )


def rule_markdown(rule: PublicRule) -> str:
    """Render repository-owned registry text, shared with the offline metadata commands."""
    return (
        f"# {rule.rule_id}: {rule.title}\n\n"
        "Generated by `make docs` from the public registry; "
        "edit registry metadata to change this page.\n\n"
        f"Default base severity: **{rule.base_severity}**. "
        "Final risk also records known size/FK modifiers.\n\n"
        f"{rule.description}\n\n"
        "## Required evidence\n\n"
        + "".join(f"- {item}\n" for item in rule.evidence_requirements)
        + "\n## Conditional alternative\n\n"
        + (rule.safe_alternative or "Unavailable.")
        + "\n\n## Boundaries and limitations\n\n"
        + "".join(f"- {item}\n" for item in rule.limitations)
        + "\n## PostgreSQL references\n\n"
        + "".join(
            f"- [PostgreSQL reference {i}]({url})\n" for i, url in enumerate(rule.references, 1)
        )
        + f"\n`schemasentry explain {rule.rule_id}` prints this metadata offline.\n"
    )
