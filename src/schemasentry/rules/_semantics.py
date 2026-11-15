"""Narrow PostgreSQL semantics; unknown syntax and catalog resolution stay unknown."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from sqlglot import ErrorLevel, exp
from sqlglot.errors import UnsupportedError

from schemasentry.migration import identifier, parse_expression
from schemasentry.snapshot import Column, Constraint, Table

TESTED_MAJORS = frozenset({13, 15, 16})

_TYPE_ALIASES = {
    "int2": "smallint",
    "smallint": "smallint",
    "int": "integer",
    "int4": "integer",
    "integer": "integer",
    "int8": "bigint",
    "bigint": "bigint",
    "varchar": "varchar",
    "character varying": "varchar",
    "text": "text",
    "numeric": "numeric",
    "decimal": "numeric",
    "float4": "real",
    "real": "real",
    "float8": "double precision",
    "double precision": "double precision",
    "timestamp": "timestamp",
    "timestamp without time zone": "timestamp",
    "timestamptz": "timestamptz",
    "timestamp with time zone": "timestamptz",
    "bool": "boolean",
    "boolean": "boolean",
    "date": "date",
}

_ACTUAL_TYPE_NAMES = frozenset(
    {
        "int2",
        "int4",
        "int8",
        "varchar",
        "text",
        "numeric",
        "float4",
        "float8",
        "timestamp",
        "timestamptz",
        "bool",
        "date",
    }
)


@dataclass(frozen=True)
class TypeInfo:
    family: str
    modifiers: tuple[int, ...] = ()


def describe_type(text: str) -> TypeInfo | None:
    if len(text) > 1024:
        return None
    raw = text.strip()
    if raw.startswith('"pg_catalog".'):
        raw = raw[len('"pg_catalog".') :]
    elif raw.lower().startswith("pg_catalog.") and not raw.startswith('"'):
        raw = raw[len("pg_catalog.") :]
    quoted = re.fullmatch(r'"([a-z0-9_]+)"(.*)', raw, flags=re.DOTALL)
    if quoted:
        if quoted[1] not in _ACTUAL_TYPE_NAMES:
            return None
        raw = quoted[1] + quoted[2]
    elif '"' in raw:
        return None
    raw = re.sub(r"\s+", " ", raw.lower())
    match = re.fullmatch(r"([a-z ]+?)(?:\s*\(([0-9, -]+)\))?", raw)
    if not match or match[1].strip() not in _TYPE_ALIASES:
        return None
    family = _TYPE_ALIASES[match[1].strip()]
    parts = match[2].split(",") if match[2] is not None else []
    if any(len(part.strip()) > 8 or not re.fullmatch(r"-?[0-9]+", part.strip()) for part in parts):
        return None
    modifiers = tuple(int(part) for part in parts)
    if family == "varchar":
        if len(modifiers) > 1 or (modifiers and not 1 <= modifiers[0] <= 10_485_760):
            return None
    elif family == "numeric":
        if len(modifiers) > 2 or (modifiers and not 1 <= modifiers[0] <= 1000):
            return None
        if len(modifiers) == 1:
            modifiers = (*modifiers, 0)
        if len(modifiers) == 2 and not 0 <= modifiers[1] <= modifiers[0]:
            return None
    elif family in {"timestamp", "timestamptz"}:
        if len(modifiers) > 1 or (modifiers and not 0 <= modifiers[0] <= 6):
            return None
    elif modifiers:
        return None
    return TypeInfo(family, modifiers)


def column_type(column: Column) -> TypeInfo | None:
    info = describe_type(column.type)
    if info is None or info.family != column.normalised_type:
        return None
    expected_length = info.modifiers[0] if info.family == "varchar" and info.modifiers else None
    return info if column.length == expected_length else None


def known_version(before: str, after: str) -> bool:
    match = re.match(r"^([0-9]{1,2})(?:\.|$|\s)", before)
    return bool(before == after and match and int(match[1]) in TESTED_MAJORS)


def render(expression: exp.Expr) -> str:
    return expression.sql(dialect="postgres", unsupported_level=ErrorLevel.RAISE)


def _catalog_function(expression: exp.Expr) -> tuple[str, tuple[exp.Expr, ...]] | None:
    if not isinstance(expression, exp.Dot) or identifier(expression.this) != "pg_catalog":
        return None
    function = expression.expression
    if not isinstance(function, exp.Anonymous):
        return None
    name = function.this
    function_name = identifier(name) if isinstance(name, exp.Identifier) else str(name).lower()
    if function_name is None:
        return None
    return function_name, tuple(function.expressions)


def _unwrap(expression: exp.Expr) -> exp.Expr:
    while isinstance(expression, exp.Paren):
        expression = expression.this
    return expression


Volatility = Literal["nonvolatile", "volatile", "unknown"]


def _volatility(expression: exp.Expr) -> Volatility:
    expression = _unwrap(expression)
    if isinstance(
        expression,
        (
            exp.Literal,
            exp.Null,
            exp.Boolean,
            exp.ByteString,
            exp.BitString,
            exp.HexString,
            exp.RawString,
        ),
    ):
        return "nonvolatile"
    if isinstance(expression, exp.Neg) and isinstance(expression.this, exp.Literal):
        return "nonvolatile" if not expression.this.is_string else "unknown"
    if isinstance(
        expression,
        (exp.CurrentTimestamp, exp.CurrentDate, exp.CurrentTime, exp.Localtimestamp, exp.Localtime),
    ):
        return "nonvolatile"
    if isinstance(expression, exp.Cast):
        info = describe_type(render(expression.args["to"]))
        # This initial contract proves only built-in text casts, not arbitrary cast functions.
        return _volatility(expression.this) if info and info.family == "text" else "unknown"
    catalog = _catalog_function(expression)
    if catalog is None:
        return "unknown"
    name, arguments = catalog
    if not arguments and name in {"random", "clock_timestamp", "timeofday"}:
        return "volatile"
    if not arguments and name in {"now", "transaction_timestamp", "statement_timestamp"}:
        return "nonvolatile"
    return "unknown"


def default_volatility(text: str, confirmed_version: bool) -> Volatility:
    expression = parse_expression(text)
    if expression is None or not confirmed_version:
        return "unknown"
    return _volatility(expression)


def default_nonnull(text: str | None, target: TypeInfo) -> bool | None:
    """Prove only reviewed built-in default assignments; None means unresolved, not NULL."""
    if text is None:
        return False
    expression = parse_expression(text)
    if expression is None:
        return None
    expression = _unwrap(expression)
    if isinstance(expression, exp.Cast):
        cast_type = describe_type(render(expression.args["to"]))
        if cast_type is None or cast_type.family != target.family:
            return None
        expression = _unwrap(expression.this)
    if isinstance(expression, exp.Null):
        return False
    if isinstance(expression, exp.Boolean):
        return True if target.family == "boolean" else None
    if isinstance(expression, exp.CurrentTimestamp) and target.family == "timestamptz":
        return True
    if isinstance(expression, exp.CurrentDate) and target.family == "date":
        return True
    catalog = _catalog_function(expression)
    if (
        catalog
        and not catalog[1]
        and catalog[0] in {"now", "transaction_timestamp", "statement_timestamp"}
    ):
        return True if target.family == "timestamptz" else None
    negative = isinstance(expression, exp.Neg)
    if negative:
        expression = expression.this
    if not isinstance(expression, exp.Literal):
        return None
    if expression.is_string:
        if negative or target.family not in {"text", "varchar"}:
            return None
        value = str(expression.this)
        return True if not target.modifiers or len(value) <= target.modifiers[0] else None
    value = ("-" if negative else "") + str(expression.this)
    integer_bits = {"smallint": 16, "integer": 32, "bigint": 64}
    if target.family in integer_bits and re.fullmatch(r"-?[0-9]{1,20}", value):
        bits = integer_bits[target.family]
        return True if -(2 ** (bits - 1)) <= int(value) < 2 ** (bits - 1) else None
    return None


def _normalise_default(expression: exp.Expr) -> exp.Expr:
    if isinstance(expression, exp.Paren):
        child: exp.Expr = expression.this
        return child.copy()
    if isinstance(expression, exp.Identifier):
        name = identifier(expression)
        if name is not None and name == name.lower():
            expression.set("this", name)
            expression.set("quoted", False)
    if _catalog_function(expression) is not None:
        unqualified = parse_expression(render(expression.expression))
        if unqualified is not None:
            return unqualified
    if isinstance(expression, exp.Cast):
        info = describe_type(render(expression.args["to"]))
        if (
            info
            and info.family == "text"
            and isinstance(expression.this, exp.Literal)
            and expression.this.is_string
        ):
            return expression.this.copy()
    if isinstance(expression, exp.DataType):
        info = describe_type(render(expression))
        if info is not None:
            suffix = "(" + ",".join(map(str, info.modifiers)) + ")" if info.modifiers else ""
            return exp.DataType.build(info.family + suffix, dialect="postgres")
    return expression


def default_signature(text: str) -> str | None:
    expression = parse_expression(text)
    if expression is None:
        return None
    try:
        return render(expression.transform(_normalise_default, copy=True))
    except (UnsupportedError, RecursionError):
        return None


def defaults_match(declared: str | None, observed: str | None) -> bool:
    if declared is None or observed is None:
        return declared is observed
    left, right = default_signature(declared), default_signature(observed)
    return left is not None and left == right


def _check(constraint: Constraint, column: str) -> tuple[str, exp.Expr] | None:
    definition = constraint.definition
    if (
        constraint.kind != "check"
        or definition is None
        or column not in constraint.columns
        or re.search(r"\b(?:NOT\s+VALID|NO\s+INHERIT)\b", definition, flags=re.IGNORECASE)
    ):
        return None
    match = re.fullmatch(r"CHECK\s*(\(.*\))", definition.strip(), flags=re.IGNORECASE | re.DOTALL)
    expression = parse_expression(match[1]) if match else None
    if expression is None or expression.find(exp.Or) is not None:
        return None
    return render(expression), expression


def _entails_nonnull(expression: exp.Expr, column: str) -> bool:
    expression = _unwrap(expression)
    if isinstance(expression, exp.And):
        return _entails_nonnull(expression.this, column) or _entails_nonnull(
            expression.expression, column
        )
    if isinstance(expression, exp.Is) and expression.args.get("negate"):
        return identifier(expression.this) == column and isinstance(expression.expression, exp.Null)
    if isinstance(expression, exp.Not) and isinstance(expression.this, exp.Is):
        return (
            not expression.this.args.get("negate")
            and identifier(expression.this.this) == column
            and isinstance(expression.this.expression, exp.Null)
        )
    return False


def nonnull_proof(before: Table, after: Table, column: str) -> bool:
    old = {
        check[0]
        for constraint in before.constraints
        if (check := _check(constraint, column)) is not None and _entails_nonnull(check[1], column)
    }
    return any(
        check[0] in old
        for constraint in after.constraints
        if (check := _check(constraint, column)) is not None and _entails_nonnull(check[1], column)
    )
