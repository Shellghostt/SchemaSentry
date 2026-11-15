"""SS007: explicit known catalog volatility, nonvolatile constructs, or uncertainty."""

from schemasentry.evidence import Evidence, Finding, RuleMetadata
from schemasentry.rules._context import RuleContext, finding
from schemasentry.rules._semantics import default_volatility

METADATA = RuleMetadata(
    rule_id="SS007",
    title="Default volatility",
    base_severity="medium",
    description="User/unqualified functions are unresolved; nonliteral does not imply volatile.",
    safe_alternative="Resolve volatility; consider a nonvolatile default and a separate backfill.",
)


def evaluate(context: RuleContext) -> list[Finding]:
    result: list[Finding] = []
    for pair in context.pairs:
        old, new = pair.before, pair.after
        if new is None or new.default is None or (old and old.default == new.default):
            continue
        declared = [
            b
            for kind in ("set_default", "add_column")
            for b in context.for_column(pair, kind)
            if b.consistent and not b.operation.conditional
        ]
        bound = declared[0] if len(declared) == 1 and context.complete_evidence else None
        text = bound.operation.default if bound is not None else new.default
        assert text is not None
        volatility = default_volatility(text, context.confirmed_version)
        if new.identity or new.generated is not None:
            volatility = "unknown"
        if volatility == "nonvolatile":
            continue
        result.append(
            finding(
                METADATA,
                pair.schema_name,
                pair.table,
                pair.name,
                "default_volatile" if volatility == "volatile" else "default_volatility_unknown",
                "high" if volatility == "volatile" else "low",
                (
                    Evidence(
                        source="migration" if bound else "snapshot",
                        detail=(
                            "Explicit known pg_catalog volatile default on a tested version."
                            if volatility == "volatile"
                            else "Default resolution is outside the confirmed allowlist."
                        ),
                        location=bound.statement.location if bound else None,
                    ),
                ),
                (
                    "User functions and arbitrary casts/operators need catalog resolution.",
                    "The small PG 13/15/16 allowlist does not cover all functions or versions.",
                    "SET DEFAULT affects future writes; SS005 reports ADD COLUMN rewrite evidence.",
                ),
            )
        )
    return result
