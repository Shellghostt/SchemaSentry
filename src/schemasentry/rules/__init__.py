"""Fixed internal SS001-SS007 registry. M4 rules and public commands are not registered."""

from collections.abc import Callable

from schemasentry.evidence import Finding, RuleMetadata
from schemasentry.rules import ss001, ss002, ss003, ss004, ss005, ss006, ss007
from schemasentry.rules._context import RuleContext

_RULES = (ss001, ss002, ss003, ss004, ss005, ss006, ss007)


def rule_metadata() -> tuple[RuleMetadata, ...]:
    return tuple(rule.METADATA for rule in _RULES)


def evaluate(context: RuleContext) -> list[Finding]:
    evaluators: tuple[Callable[[RuleContext], list[Finding]], ...] = tuple(
        rule.evaluate for rule in _RULES
    )
    return [finding for evaluator in evaluators for finding in evaluator(context)]
