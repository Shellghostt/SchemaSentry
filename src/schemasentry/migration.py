"""Bounded PostgreSQL SQL evidence, parsed as data and never executed."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar, Literal

from sqlglot import ErrorLevel, Token, TokenType, exp
from sqlglot.dialects.postgres import Postgres
from sqlglot.errors import ParseError, TokenError, UnsupportedError
from sqlglot.parsers.postgres import PostgresParser

from schemasentry.errors import ToolError
from schemasentry.evidence import EvidenceModel, SourceLocation

MAX_SQL_BYTES = 256 * 1024
MAX_STATEMENTS = 128
MAX_TOKENS = 20_000
MAX_NESTING = 64

OperationKind = Literal[
    "alter_type",
    "set_not_null",
    "drop_not_null",
    "set_default",
    "drop_default",
    "add_column",
    "drop_column",
    "rename_column",
    "vacuum_full",
]


class MigrationOperation(EvidenceModel):
    kind: OperationKind
    schema_name: str | None
    table: str
    column: str | None = None
    new_column: str | None = None
    target_type: str | None = None
    using: str | None = None
    default: str | None = None
    nullable: bool | None = None
    conditional: bool = False


class MigrationStatement(EvidenceModel):
    status: Literal["supported", "unsupported", "parse_error"]
    text: str
    location: SourceLocation
    operations: tuple[MigrationOperation, ...] = ()
    wrapper: Literal["begin", "commit", "rollback"] | None = None
    detail: str | None = None


class MigrationError(EvidenceModel):
    kind: Literal["limit_exceeded", "parse_error", "invalid_utf8"]
    detail: str
    location: SourceLocation | None = None


class Migration(EvidenceModel):
    text: str
    statements: tuple[MigrationStatement, ...]
    errors: tuple[MigrationError, ...] = ()


class _QuietPostgres(Postgres):
    class Parser(PostgresParser):
        def _warn_unsupported(self) -> None:
            # SQLGlot's fallback warning includes raw SQL. Return it as bounded data instead.
            pass


class _EvidenceTokenizer(Postgres.Tokenizer):
    # Command fallback otherwise hides its payload as one token, defeating token/depth limits.
    COMMANDS: ClassVar[set[TokenType]] = set()


class _InvalidEvidence(ValueError):
    pass


def _checked_tokens(text: str) -> list[Token]:
    if len(text) > MAX_SQL_BYTES or len(text.encode("utf-8")) > MAX_SQL_BYTES:
        raise _InvalidEvidence("migration exceeds 256 KiB of UTF-8 SQL")
    tokens = _EvidenceTokenizer(dialect=Postgres()).tokenize(text)
    if len(tokens) > MAX_TOKENS:
        raise _InvalidEvidence("migration exceeds 20,000 tokens")
    stack: list[TokenType] = []
    closes = {
        TokenType.L_PAREN: TokenType.R_PAREN,
        TokenType.L_BRACKET: TokenType.R_BRACKET,
        TokenType.L_BRACE: TokenType.R_BRACE,
    }
    for token in tokens:
        kind = token.token_type
        if kind in closes:
            stack.append(closes[kind])
            if len(stack) > MAX_NESTING:
                raise _InvalidEvidence("migration exceeds 64 levels of delimiter nesting")
        elif kind in closes.values() and (not stack or stack.pop() != kind):
            raise TokenError("unmatched SQL delimiter")
    if stack:
        raise TokenError("unclosed SQL delimiter")
    return tokens


def fold_identifier(name: str) -> str:
    """PostgreSQL's UTF-8 identifier normalization folds ASCII, not Unicode case."""
    return name.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))


def identifier(node: exp.Expr | None) -> str | None:
    """PostgreSQL folds unquoted names to lower case, while quoted names are exact."""
    if isinstance(node, exp.Column):
        if any(node.args.get(key) for key in ("table", "db", "catalog")):
            return None
        node = node.this
    if not isinstance(node, exp.Identifier):
        return None
    name = node.name
    return name if node.args.get("quoted") else fold_identifier(name)


def _render(node: exp.Expr) -> str:
    return node.sql(dialect="postgres", unsupported_level=ErrorLevel.RAISE)


def parse_expression(text: str) -> exp.Expr | None:
    """Parse one bounded expression without accepting trailing statements or SELECT clauses."""
    try:
        _checked_tokens(text)
        trees = _QuietPostgres().parse("SELECT " + text)
        if len(trees) != 1 or not isinstance(trees[0], exp.Select):
            return None
        tree = trees[0]
        if len(tree.expressions) != 1 or any(
            value for key, value in tree.args.items() if key != "expressions"
        ):
            return None
        expression = tree.expressions[0]
        return expression if isinstance(expression, exp.Expr) else None
    except (ParseError, TokenError, _InvalidEvidence, UnicodeError, RecursionError):
        return None


def _location(text: str, start: int, end: int) -> SourceLocation:
    return SourceLocation(
        start=start,
        end=end,
        line=text.count("\n", 0, start) + 1,
        column=start - text.rfind("\n", 0, start),
    )


def _groups(tokens: list[Token]) -> list[tuple[list[Token], int]]:
    result: list[tuple[list[Token], int]] = []
    current: list[Token] = []
    for token in tokens:
        if token.token_type == TokenType.SEMICOLON:
            if current:
                result.append((current, token.end + 1))
                current = []
        else:
            current.append(token)
    if current:
        result.append((current, current[-1].end + 1))
    if len(result) > MAX_STATEMENTS:
        raise _InvalidEvidence("migration exceeds 128 statements")
    return result


def _vacuum(tokens: list[Token]) -> tuple[MigrationOperation, ...] | None:
    if tokens[0].token_type != TokenType.COMMAND or tokens[0].text.upper() != "VACUUM":
        return None
    offset = 1
    if len(tokens) > 3 and [t.token_type for t in tokens[1:4]] == [
        TokenType.L_PAREN,
        TokenType.FULL,
        TokenType.R_PAREN,
    ]:
        offset = 4
    elif len(tokens) > 1 and tokens[1].token_type == TokenType.FULL:
        offset = 2
    else:
        return None
    names = tokens[offset:]
    valid_name = {TokenType.VAR, TokenType.IDENTIFIER}
    if len(names) == 1 and names[0].token_type in valid_name:
        schema, table = None, names[0]
    elif (
        len(names) == 3
        and names[0].token_type in valid_name
        and names[1].token_type == TokenType.DOT
        and names[2].token_type in valid_name
    ):
        schema, table = names[0], names[2]
    else:
        return None

    def name(token: Token) -> str:
        return (
            token.text if token.token_type == TokenType.IDENTIFIER else fold_identifier(token.text)
        )

    return (
        MigrationOperation(
            kind="vacuum_full", schema_name=name(schema) if schema else None, table=name(table)
        ),
    )


def _action(
    action: exp.Expr, schema: str | None, table: str, conditional: bool
) -> tuple[MigrationOperation, ...] | None:
    conditional = conditional or bool(action.args.get("exists"))
    if isinstance(action, exp.ColumnDef):
        column = identifier(action.this)
        dtype = action.args.get("kind")
        if column is None or not isinstance(dtype, exp.DataType):
            return None
        default: str | None = None
        nullable = True
        seen: set[str] = set()
        for constraint in action.args.get("constraints") or ():
            kind = constraint.args.get("kind")
            if isinstance(kind, exp.NotNullColumnConstraint) and "nullability" not in seen:
                nullable = bool(kind.args.get("allow_null"))
                seen.add("nullability")
            elif isinstance(kind, exp.DefaultColumnConstraint) and "default" not in seen:
                default = _render(kind.this)
                seen.add("default")
            else:
                return None
        if any(
            value
            for key, value in action.args.items()
            if key not in {"this", "kind", "constraints", "exists"}
        ):
            return None
        return (
            MigrationOperation(
                kind="add_column",
                schema_name=schema,
                table=table,
                column=column,
                target_type=_render(dtype),
                default=default,
                nullable=nullable,
                conditional=conditional,
            ),
        )
    if isinstance(action, exp.AlterColumn):
        column = identifier(action.this)
        if column is None or any(
            value
            for key, value in action.args.items()
            if key not in {"this", "dtype", "using", "allow_null", "default", "drop", "exists"}
        ):
            return None
        dtype = action.args.get("dtype")
        default_node = action.args.get("default")
        using_node = action.args.get("using")
        if isinstance(dtype, exp.DataType):
            operation: OperationKind = "alter_type"
        elif action.args.get("allow_null") is not None:
            operation = "drop_not_null" if action.args["allow_null"] else "set_not_null"
        elif isinstance(default_node, exp.Expr):
            operation = "set_default"
        elif action.args.get("drop"):
            operation = "drop_default"
        else:
            return None
        return (
            MigrationOperation(
                kind=operation,
                schema_name=schema,
                table=table,
                column=column,
                target_type=_render(dtype) if isinstance(dtype, exp.DataType) else None,
                using=_render(using_node) if isinstance(using_node, exp.Expr) else None,
                default=_render(default_node) if isinstance(default_node, exp.Expr) else None,
                nullable=action.args.get("allow_null"),
                conditional=conditional,
            ),
        )
    if isinstance(action, exp.RenameColumn):
        column, target = identifier(action.this), identifier(action.args.get("to"))
        if column is None or target is None:
            return None
        return (
            MigrationOperation(
                kind="rename_column",
                schema_name=schema,
                table=table,
                column=column,
                new_column=target,
                conditional=conditional,
            ),
        )
    if isinstance(action, exp.Drop) and action.kind == "COLUMN":
        if any(
            value
            for key, value in action.args.items()
            if key not in {"tables", "kind", "exists", "restrict"}
        ):
            return None
        columns = [identifier(node) for node in action.args.get("tables") or ()]
        if not columns or any(column is None for column in columns):
            return None
        return tuple(
            MigrationOperation(
                kind="drop_column",
                schema_name=schema,
                table=table,
                column=column,
                conditional=conditional,
            )
            for column in columns
        )
    return None


def _alter(tree: exp.Alter) -> tuple[MigrationOperation, ...] | None:
    target = tree.this
    if tree.kind != "TABLE" or not isinstance(target, exp.Table) or target.args.get("catalog"):
        return None
    schema = identifier(target.args.get("db"))
    table = identifier(target.this)
    if table is None or any(
        value
        for key, value in tree.args.items()
        if key not in {"this", "kind", "actions", "exists", "only"}
    ):
        return None
    operations: list[MigrationOperation] = []
    for action in tree.args.get("actions") or ():
        parsed = _action(action, schema, table, bool(tree.args.get("exists")))
        if parsed is None:
            return None
        operations.extend(parsed)
    return tuple(operations) if operations else None


def _statement(text: str, location: SourceLocation, tokens: list[Token]) -> MigrationStatement:
    source = text[location.start : location.end]
    try:
        operations = _vacuum(tokens)
        trees = _QuietPostgres().parse(source)
        if len(trees) != 1 or trees[0] is None:
            raise ParseError("expected one statement")
        tree = trees[0]
        wrapper: Literal["begin", "commit", "rollback"] | None = None
        if isinstance(tree, exp.Transaction):
            wrapper = "begin"
        elif isinstance(tree, exp.Commit):
            wrapper = "commit"
        elif isinstance(tree, exp.Rollback) and not tree.args.get("savepoint"):
            wrapper = "rollback"
        elif isinstance(tree, exp.Alter):
            operations = _alter(tree)
        if (
            isinstance(tree, exp.Command)
            and tokens[0].token_type == TokenType.ALTER
            and tokens[-1].text.upper() in {"TYPE", "USING", "DEFAULT", "TO", "COLUMN", "TABLE"}
        ):
            raise ParseError("incomplete ALTER statement")
        supported = operations is not None or wrapper is not None
        return MigrationStatement(
            status="supported" if supported else "unsupported",
            text=source,
            location=location,
            operations=operations or (),
            wrapper=wrapper,
            detail=None if supported else "statement is outside the supported M3 SQL subset",
        )
    except (ParseError, TokenError, UnsupportedError, RecursionError):
        return MigrationStatement(
            status="parse_error",
            text=source,
            location=location,
            detail="cannot parse SQL statement",
        )


def parse_migration(text: str) -> Migration:
    try:
        tokens = _checked_tokens(text)
        groups = _groups(tokens)
    except _InvalidEvidence as exc:
        return Migration(
            text="", statements=(), errors=(MigrationError(kind="limit_exceeded", detail=str(exc)),)
        )
    except UnicodeError:
        return Migration(
            text="",
            statements=(),
            errors=(MigrationError(kind="invalid_utf8", detail="migration must be valid UTF-8"),),
        )
    except (TokenError, RecursionError):
        return Migration(
            text=text,
            statements=(),
            errors=(MigrationError(kind="parse_error", detail="cannot tokenize SQL migration"),),
        )
    statements = tuple(
        _statement(text, _location(text, group[0].start, end), group) for group, end in groups
    )
    errors = tuple(
        MigrationError(kind="parse_error", detail="cannot parse SQL statement", location=s.location)
        for s in statements
        if s.status == "parse_error"
    )
    return Migration(text=text, statements=statements, errors=errors)


def load_migration(path: Path) -> Migration:
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_SQL_BYTES + 1)
        if len(raw) > MAX_SQL_BYTES:
            return Migration(
                text="",
                statements=(),
                errors=(MigrationError(kind="limit_exceeded", detail="migration exceeds 256 KiB"),),
            )
        return parse_migration(raw.decode("utf-8"))
    except UnicodeError:
        return Migration(
            text="",
            statements=(),
            errors=(MigrationError(kind="invalid_utf8", detail="migration must be valid UTF-8"),),
        )
    except OSError:
        raise ToolError("cannot read migration evidence file") from None
