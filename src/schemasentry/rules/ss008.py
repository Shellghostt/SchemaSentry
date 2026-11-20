"""SS008: eligible CHECK/FK validation requests and explicitly known catalog validity."""

from __future__ import annotations

from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from schemasentry.catalog_models import ConstraintValidity
from schemasentry.evidence import Effects, Evidence, Finding, Notice, RuleMetadata
from schemasentry.m4_migration import AssessmentOperation, parse_assessment_migration
from schemasentry.migration import _checked_tokens, _QuietPostgres, fold_identifier
from schemasentry.rules._m4_context import AssessmentContext, m4_finding
from schemasentry.snapshot import Constraint

METADATA = RuleMetadata(
    rule_id="SS008",
    title="CHECK or foreign key validation requested",
    base_severity="high",
    description=(
        "Immediate validation can scan existing rows while adding an eligible CHECK/FK constraint."
    ),
    safe_alternative=(
        "For eligible CHECK/FK only, consider ADD CONSTRAINT ... NOT VALID"
        ", then VALIDATE CONSTRAINT separately. Both stages still acquire "
        "locks and NOT VALID enforces new writes. This is not an alternati"
        "ve for UNIQUE, PRIMARY KEY or NOT NULL."
    ),
)


def _expression(text: str) -> str | None:
    try:
        _checked_tokens(text)
        trees = _QuietPostgres().parse("SELECT " + text)
        if (
            len(trees) != 1
            or not isinstance(trees[0], exp.Select)
            or len(trees[0].expressions) != 1
        ):
            return None
        tree = trees[0].expressions[0]
        while isinstance(tree, exp.Paren):
            tree = tree.this
        for node in tree.find_all(exp.Identifier):
            if not node.args.get("quoted"):
                node.set("this", fold_identifier(node.name))
        return str(tree.sql(dialect="postgres"))
    except (ValueError, RecursionError, ParseError, TokenError):
        return None


def _consistent(
    context: AssessmentContext, operation: AssessmentOperation, constraint: Constraint
) -> bool:
    if not operation.simple or tuple(constraint.columns) != operation.columns:
        return False
    if constraint.kind == "foreign_key":
        catalog = context.after.catalog_evidence
        if catalog is None:
            return False
        schema = (
            operation.referenced_schema
            if operation.referenced_schema is not None
            else context.default_schema
        )
        return any(
            fact.schema_name == context.schema(operation)
            and fact.table == operation.target
            and fact.name == operation.name
            and fact.target_schema == schema
            and fact.target_table == operation.referenced_table
            and fact.target_columns == operation.referenced_columns
            for fact in catalog.incoming_foreign_keys
        )
    if constraint.definition is None or operation.definition is None:
        return False
    parsed = parse_assessment_migration(
        "ALTER TABLE public._binding ADD CONSTRAINT _binding " + constraint.definition
    )
    if len(parsed.operations) != 1 or parsed.operations[0].definition is None:
        return False
    left, right = parsed.operations[0].definition, operation.definition
    if not left.startswith("CHECK (") or not right.startswith("CHECK ("):
        return False
    return (
        _expression(left[len("CHECK (") : -1]) == _expression(right[len("CHECK (") : -1])
        and _expression(right[len("CHECK (") : -1]) is not None
    )


def _validity(
    context: AssessmentContext, schema: str, table: str, name: str, *, before: bool = False
) -> ConstraintValidity | None:
    catalog = (context.before if before else context.after).catalog_evidence
    if catalog is None:
        return None
    return next(
        (
            fact
            for fact in catalog.constraint_validity
            if (fact.schema_name, fact.table, fact.name) == (schema, table, name)
        ),
        None,
    )


def _same_definition(before: Constraint, after: Constraint) -> bool:
    # pg_get_constraintdef includes NOT VALID until validation succeeds.
    return before.model_copy(
        update={
            "definition": before.definition.removesuffix(" NOT VALID")
            if before.definition
            else None
        }
    ) == after.model_copy(
        update={
            "definition": after.definition.removesuffix(" NOT VALID") if after.definition else None
        }
    )


def evaluate(context: AssessmentContext) -> tuple[list[Finding], list[Notice]]:
    findings: list[Finding] = []
    notices: list[Notice] = []
    for table in context.after.tables:
        prior = context.table(table.schema_name, table.name, before=True)
        old = {constraint.name: constraint for constraint in prior.constraints} if prior else {}
        for constraint in table.constraints:
            if constraint.kind not in ("check", "foreign_key"):
                continue
            previous = old.get(constraint.name)
            is_new = previous is None
            catalog = context.after.catalog_evidence
            ordinary = bool(
                catalog
                and any(
                    (relation.schema_name, relation.table, relation.kind)
                    == (table.schema_name, table.name, "ordinary")
                    for relation in catalog.relations
                )
            )
            validity = _validity(context, table.schema_name, table.name, constraint.name)
            prior_validity = _validity(
                context, table.schema_name, table.name, constraint.name, before=True
            )
            operations = context.for_object(
                "add_constraint", table.schema_name, table.name, constraint.name
            )
            validators = context.for_object(
                "validate_constraint", table.schema_name, table.name, constraint.name
            )
            transition = bool(
                prior_validity and validity and not prior_validity.validated and validity.validated
            )
            if not is_new and not transition and not operations and not validators:
                continue
            operation = operations[0] if len(operations) == 1 else None
            validator = validators[0] if len(validators) == 1 else None
            known_addition = bool(
                is_new
                and ordinary
                and operation
                and operation.simple
                and validity
                and context.confirmed
                and operation.transaction not in ("rolled_back", "unknown")
                and operation.constraint_kind == constraint.kind
                and _consistent(context, operation, constraint)
            )
            known_validation = bool(
                validator
                and ordinary
                and validator.simple
                and validator.transaction not in ("rolled_back", "unknown")
                and context.confirmed
                and validity
                and validity.validated
                and (
                    (
                        previous
                        and prior_validity
                        and not operations
                        and _same_definition(previous, constraint)
                    )
                    or (
                        known_addition
                        and operation
                        and validator.location.start > operation.location.start
                    )
                )
            )
            if known_validation and prior_validity and prior_validity.validated:
                notices.append(
                    Notice(
                        kind="constraint_already_valid",
                        detail=(
                            "The retained constraint was already validated; "
                            "no new validation scan is established."
                        ),
                        location=validator.location if validator else None,
                    )
                )
                continue
            if (
                known_addition
                and operation is not None
                and validity is not None
                and operation.not_valid
                and not validity.validated
                and not validators
            ):
                notices.append(
                    Notice(
                        kind="not_valid_constraint_locks",
                        detail=(
                            "NOT VALID avoids initial validation scanning but retains locks an"
                            "d new-write enforcement."
                        ),
                        location=operation.location,
                    )
                )
                continue
            requested = bool(
                known_validation
                or (
                    known_addition
                    and operation is not None
                    and validity is not None
                    and not operation.not_valid
                    and validity.validated
                    and not validators
                )
            )
            evidence: tuple[Evidence, ...] = (
                Evidence(
                    source="snapshot",
                    detail=(
                        f"{'Added' if is_new else 'Retained'} {constraint.kind} "
                        f"constraint {constraint.name!r}; "
                        f"captured validation is {'known' if validity else 'unknown'}."
                    ),
                ),
            )
            evidence += tuple(
                context.migration_evidence(request)
                for request in sorted((*operations, *validators), key=lambda op: op.location.start)
            )
            finding = m4_finding(
                METADATA,
                table.schema_name,
                table.name,
                constraint.name,
                "constraint_validation_requested" if requested else "constraint_validation_unknown",
                "high" if requested else "low",
                evidence,
                (
                    "SQL is requested evidence, not proof that it executed.",
                    (
                        "Validation can fail on existing rows; captured statistics do not "
                        "provide a duration."
                    ),
                    "Foreign-key binding requires the referenced table scope.",
                    "Confirmed constraint effects require a supported ordinary relation.",
                ),
            )
            if requested:
                finding = finding.model_copy(
                    update={
                        "effects": Effects(
                            lock_level=(
                                "share_update_exclusive"
                                if not is_new
                                else "access_exclusive"
                                if constraint.kind == "check"
                                else "share_row_exclusive"
                            ),
                            scan="required",
                            rewrite="not_required",
                        )
                    }
                )
            findings.append(finding)
    return findings, notices
