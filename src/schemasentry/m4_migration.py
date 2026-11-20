"""Additional bounded M4 SQL evidence; the M3 parser/result contract is unchanged."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from sqlglot import exp
from sqlglot.errors import ParseError
from sqlglot.tokenizer_core import TokenType

from schemasentry.evidence import EvidenceModel, Notice, SourceLocation
from schemasentry.migration import (
    Migration,
    MigrationStatement,
    _checked_tokens,
    _QuietPostgres,
    fold_identifier,
    identifier,
    load_migration,
    parse_migration,
)


class AssessmentOperation(EvidenceModel):
    kind: Literal[
        "add_constraint",
        "validate_constraint",
        "create_index",
        "enum_add",
        "enum_rename",
        "enum_create",
        "enum_drop",
    ]
    schema_name: str | None
    target: str
    name: str | None = None
    constraint_kind: Literal["check", "foreign_key"] | None = None
    not_valid: bool = False
    columns: tuple[str, ...] = ()
    definition: str | None = None
    referenced_schema: str | None = None
    referenced_table: str | None = None
    referenced_columns: tuple[str, ...] = ()
    unique: bool = False
    concurrent: bool = False
    simple: bool = True
    old_label: str | None = None
    new_label: str | None = None
    labels: tuple[str, ...] = ()
    location: SourceLocation
    transaction: Literal["outside", "explicit", "rolled_back", "unknown"] = "outside"


class AssessmentMigration(EvidenceModel):
    legacy: Migration
    operations: tuple[AssessmentOperation, ...]
    superseded_starts: tuple[int, ...]
    notices: tuple[Notice, ...] = ()

    def classification_view(self) -> Migration:
        """Recognized M4 locations are supported, with no invented M3 operations."""
        starts = set(self.superseded_starts)
        return self.legacy.model_copy(
            update={
                "statements": tuple(
                    statement.model_copy(
                        update={"status": "supported", "operations": (), "detail": None}
                    )
                    if statement.location.start in starts
                    else statement
                    for statement in self.legacy.statements
                ),
                "errors": tuple(
                    error
                    for error in self.legacy.errors
                    if error.location is None or error.location.start not in starts
                ),
            }
        )


def _table(node: exp.Expr | None) -> tuple[str | None, str] | None:
    if not isinstance(node, exp.Table) or node.args.get("catalog") is not None:
        return None
    name = identifier(node.this)
    schema = identifier(node.args.get("db"))
    return (schema, name) if name is not None else None


def _tree(text: str) -> exp.Expr | None:
    try:
        trees = _QuietPostgres().parse(text)
        return trees[0] if len(trees) == 1 else None
    except (ParseError, ValueError, RecursionError):
        return None


def _enum_alter(statement: MigrationStatement) -> AssessmentOperation | None:
    tokens = [
        token
        for token in _checked_tokens(statement.text)
        if token.token_type != TokenType.SEMICOLON
    ]
    if len(tokens) < 6 or [token.text.upper() for token in tokens[:2]] != ["ALTER", "TYPE"]:
        return None
    action = next(
        (i for i in range(3, len(tokens)) if tokens[i].text.upper() in ("ADD", "RENAME")), None
    )
    if action is None:
        return None
    target_text = statement.text[tokens[2].start : tokens[action - 1].end + 1]
    target_tree = _tree("DROP TYPE " + target_text)
    if not isinstance(target_tree, exp.Drop) or len(target_tree.args.get("tables") or ()) != 1:
        return None
    target = _table(target_tree.args["tables"][0])
    if target is None:
        return None
    words = tokens[action:]
    if words[0].text.upper() == "RENAME":
        if len(words) != 5 or words[1].text.upper() != "VALUE" or words[3].text.upper() != "TO":
            return None
        if words[2].token_type != TokenType.STRING or words[4].token_type != TokenType.STRING:
            return None
        return AssessmentOperation(
            kind="enum_rename",
            schema_name=target[0],
            target=target[1],
            old_label=words[2].text,
            new_label=words[4].text,
            location=statement.location,
        )
    if (
        len(words) != 3
        or words[1].text.upper() != "VALUE"
        or words[2].token_type != TokenType.STRING
    ):
        return None
    return AssessmentOperation(
        kind="enum_add",
        schema_name=target[0],
        target=target[1],
        new_label=words[2].text,
        location=statement.location,
    )


def _validation(statement: MigrationStatement) -> AssessmentOperation | None:
    tokens = [
        token
        for token in _checked_tokens(statement.text)
        if token.token_type != TokenType.SEMICOLON
    ]
    if (
        len(tokens) < 6
        or tokens[0].token_type != TokenType.ALTER
        or tokens[1].token_type != TokenType.TABLE
        or tokens[-3].token_type != TokenType.VAR
        or tokens[-3].text.upper() != "VALIDATE"
        or tokens[-2].token_type != TokenType.CONSTRAINT
        or tokens[-1].token_type not in (TokenType.VAR, TokenType.IDENTIFIER)
    ):
        return None
    target_text = statement.text[tokens[2].start : tokens[-4].end + 1]
    tree = _tree("DROP TABLE " + target_text)
    if not isinstance(tree, exp.Drop) or tree.args.get("exists"):
        return None
    tables = tree.args.get("tables") or []
    target = _table(tables[0]) if len(tables) == 1 else None
    if target is None:
        return None
    name = tokens[-1].text
    if tokens[-1].token_type != TokenType.IDENTIFIER:
        name = fold_identifier(name)
    return AssessmentOperation(
        kind="validate_constraint",
        schema_name=target[0],
        target=target[1],
        name=name,
        location=statement.location,
    )


def _additional(statement: MigrationStatement) -> AssessmentOperation | None:
    validation = _validation(statement)
    if validation is not None:
        return validation
    tree = _tree(statement.text)
    if isinstance(tree, exp.Alter) and str(tree.args.get("kind")).upper() == "TABLE":
        target = _table(tree.this)
        actions = tree.args.get("actions") or []
        if target is None or len(actions) != 1 or not isinstance(actions[0], exp.AddConstraint):
            return None
        nodes = actions[0].expressions
        if len(nodes) != 1 or not isinstance(nodes[0], exp.Constraint):
            return None
        name = identifier(nodes[0].this)
        definitions = nodes[0].expressions
        if name is None or len(definitions) != 1:
            return None
        definition = definitions[0]
        if isinstance(definition, exp.CheckColumnConstraint):
            kind: Literal["check", "foreign_key"] = "check"
            columns = tuple(
                sorted(
                    {identifier(column.this) or "" for column in definition.find_all(exp.Column)}
                )
            )
        elif isinstance(definition, exp.ForeignKey):
            kind = "foreign_key"
            names = [identifier(node) for node in definition.expressions]
            if any(name is None for name in names):
                return None
            columns = tuple(name for name in names if name is not None)
        else:
            return None
        referenced: tuple[str | None, str] | None = None
        referenced_columns: tuple[str, ...] = ()
        if isinstance(definition, exp.ForeignKey):
            reference = definition.args.get("reference")
            if not isinstance(reference, exp.Reference) or not isinstance(
                reference.this, exp.Schema
            ):
                return None
            referenced = _table(reference.this.this)
            if referenced is None:
                return None
            reference_names = [identifier(node) for node in reference.this.expressions]
            if any(name is None for name in reference_names):
                return None
            referenced_columns = tuple(name for name in reference_names if name is not None)
        return AssessmentOperation(
            kind="add_constraint",
            schema_name=target[0],
            target=target[1],
            name=name,
            constraint_kind=kind,
            not_valid=bool(tree.args.get("not_valid")),
            columns=columns,
            definition=("CHECK (" + definition.this.sql(dialect="postgres") + ")")
            if isinstance(definition, exp.CheckColumnConstraint)
            else definition.sql(dialect="postgres"),
            referenced_schema=referenced[0] if referenced else None,
            referenced_table=referenced[1] if referenced else None,
            referenced_columns=referenced_columns,
            simple=not any(tree.args.get(flag) for flag in ("exists", "only", "cascade")),
            location=statement.location,
        )
    if isinstance(tree, exp.Create) and str(tree.args.get("kind")).upper() == "INDEX":
        if not isinstance(tree.this, exp.Index):
            return None
        target = _table(tree.this.args.get("table"))
        name = identifier(tree.this.this)
        params = tree.this.args.get("params")
        if target is None or name is None or not isinstance(params, exp.IndexParameters):
            return None
        index_columns: list[str] = []
        simple = not any(tree.args.get(flag) for flag in ("exists", "replace"))
        for ordered in params.args.get("columns") or []:
            if isinstance(ordered, exp.Ordered) and (
                ordered.args.get("desc") or ordered.args.get("nulls_first")
            ):
                simple = False
            node = ordered.this if isinstance(ordered, exp.Ordered) else ordered
            if (
                not isinstance(node, exp.Column)
                or node.args.get("table")
                or identifier(node.this) is None
            ):
                simple = False
            else:
                index_columns.append(identifier(node.this) or "")
        if any(
            params.args.get(flag)
            for flag in ("where", "include", "with", "using", "tablespace", "with_storage")
        ):
            simple = False
        return AssessmentOperation(
            kind="create_index",
            schema_name=target[0],
            target=target[1],
            name=name,
            columns=tuple(index_columns),
            unique=bool(tree.args.get("unique")),
            concurrent=bool(tree.args.get("concurrently")),
            simple=simple,
            location=statement.location,
        )
    if isinstance(tree, exp.Create) and str(tree.args.get("kind")).upper() == "TYPE":
        target = _table(tree.this)
        datatype = tree.args.get("expression")
        if (
            target is None
            or not isinstance(datatype, exp.DataType)
            or datatype.this != exp.DType.ENUM
        ):
            return None
        if any(
            not isinstance(label, exp.Literal) or not label.is_string
            for label in datatype.expressions
        ):
            return None
        return AssessmentOperation(
            kind="enum_create",
            schema_name=target[0],
            target=target[1],
            labels=tuple(label.this for label in datatype.expressions),
            location=statement.location,
            simple=not any(tree.args.get(flag) for flag in ("exists", "replace")),
        )
    if isinstance(tree, exp.Drop) and str(tree.args.get("kind")).upper() == "TYPE":
        tables = tree.args.get("tables") or []
        target = _table(tables[0]) if len(tables) == 1 else None
        if target is None:
            return None
        return AssessmentOperation(
            kind="enum_drop",
            schema_name=target[0],
            target=target[1],
            location=statement.location,
            simple=not any(tree.args.get(flag) for flag in ("exists", "cascade")),
        )
    return _enum_alter(statement)


def _extend(legacy: Migration) -> AssessmentMigration:
    operations: list[AssessmentOperation] = []
    superseded: list[int] = []
    notices: list[Notice] = []
    active = False
    block_start = 0
    block_has_evidence = False
    for statement in legacy.statements:
        if statement.wrapper == "begin":
            if active:
                notices.append(
                    Notice(
                        kind="transaction_context_unsupported",
                        detail="Nested transaction wrappers are unavailable.",
                        location=statement.location,
                    )
                )
            active, block_start, block_has_evidence = True, len(operations), False
            continue
        if statement.wrapper in ("commit", "rollback"):
            if not active:
                notices.append(
                    Notice(
                        kind="transaction_context_unsupported",
                        detail="Transaction end has no matching BEGIN.",
                        location=statement.location,
                    )
                )
            if statement.wrapper == "rollback":
                if active and block_has_evidence:
                    notices.append(
                        Notice(
                            kind="unavailable_m4_transaction",
                            detail=(
                                "Requested statements were rolled back; "
                                "their effects are unconfirmed."
                            ),
                            location=statement.location,
                        )
                    )
                operations[block_start:] = [
                    op.model_copy(update={"transaction": "rolled_back"})
                    for op in operations[block_start:]
                ]
            active = False
            continue
        if active and (statement.operations or statement.status != "supported"):
            block_has_evidence = True
        if statement.status == "supported":
            continue
        try:
            additional = _additional(statement)
        except (ValueError, RecursionError):
            additional = None
        if additional is not None:
            operations.append(
                additional.model_copy(update={"transaction": "explicit" if active else "outside"})
            )
            superseded.append(statement.location.start)
    if active:
        notices.append(
            Notice(kind="transaction_context_unsupported", detail="BEGIN has no matching end.")
        )
    return AssessmentMigration(
        legacy=legacy,
        operations=tuple(operations),
        superseded_starts=tuple(superseded),
        notices=tuple(notices),
    )


def parse_assessment_migration(text: str) -> AssessmentMigration:
    return _extend(parse_migration(text))


def load_assessment_migration(path: Path) -> AssessmentMigration:
    return _extend(load_migration(path))
