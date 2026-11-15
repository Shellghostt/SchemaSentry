"""SS004: prove FK equality coverage from valid, complete leading btree keys."""

import re

from schemasentry.evidence import Evidence, Finding, RuleMetadata
from schemasentry.migration import fold_identifier
from schemasentry.rules._context import RuleContext, finding
from schemasentry.rules._semantics import TypeInfo, column_type
from schemasentry.snapshot import Index, Table

METADATA = RuleMetadata(
    rule_id="SS004",
    title="Foreign-key supporting index unproven",
    base_severity="medium",
    description="PostgreSQL does not automatically index foreign-key referencing columns.",
    safe_alternative=(
        "Review an index with the FK columns as leading equality keys. "
        "Plan index creation locks separately."
    ),
)

_IDENTIFIER = r'(?:"(?:[^"]|"")*"|(?:[^\W\d]|_)[\w$]*)'
_NAME = re.compile(rf"^({_IDENTIFIER})(.*)$", flags=re.DOTALL)
_ORDER = re.compile(r"^(?:(?:ASC|DESC)\s*)?(?:NULLS\s+(?:FIRST|LAST))?$", flags=re.IGNORECASE)
_QUALIFIED = re.compile(rf"^({_IDENTIFIER})\.({_IDENTIFIER})$")
_DECORATIONS = re.compile(
    rf"^(?:(?:ASC|DESC)\s*)?(?:NULLS\s+(?:FIRST|LAST)\s*)?"
    rf"(?:COLLATE\s+(?P<collation>{_IDENTIFIER}\.{_IDENTIFIER})\s*)?"
    rf"(?:OPCLASS\s+(?P<opclass>{_IDENTIFIER}\.{_IDENTIFIER}))?$",
    flags=re.IGNORECASE,
)
_DEFAULT_OPCLASSES = {
    "smallint": "int2_ops",
    "integer": "int4_ops",
    "bigint": "int8_ops",
    "text": "text_ops",
    "varchar": "text_ops",
    "numeric": "numeric_ops",
    "real": "float4_ops",
    "double precision": "float8_ops",
    "boolean": "bool_ops",
    "date": "date_ops",
    "timestamp": "timestamp_ops",
    "timestamptz": "timestamptz_ops",
}


def _name(text: str) -> str:
    return text[1:-1].replace('""', '"') if text.startswith('"') else fold_identifier(text)


def _catalog_name(text: str) -> str | None:
    match = _QUALIFIED.fullmatch(text)
    return _name(match[2]) if match and _name(match[1]) == "pg_catalog" else None


def _key(
    text: str, types: dict[str, TypeInfo | None], confirmed_version: bool
) -> tuple[str | None, bool]:
    match = _NAME.fullmatch(text.strip())
    if not match:
        return None, False
    name, suffix = match[1], match[2].strip()
    column = _name(name)
    if _ORDER.fullmatch(suffix):
        return column, True
    modifiers = _DECORATIONS.fullmatch(suffix)
    info = types.get(column)
    if not modifiers or info is None or not confirmed_version:
        return column, False
    collation, opclass = modifiers["collation"], modifiers["opclass"]
    if collation and (
        info.family not in {"text", "varchar"} or _catalog_name(collation) != "default"
    ):
        return column, False
    if opclass and _catalog_name(opclass) != _DEFAULT_OPCLASSES.get(info.family):
        return column, False
    return column, True


def _coverage(index: Index, columns: list[str], table: Table, confirmed_version: bool) -> str:
    """proven, unknown (a potentially usable candidate), or unusable."""
    if not index.valid:
        return "unusable"
    if index.keys is None:
        return "unknown" if set(columns) <= set(index.columns) else "unusable"
    if len(index.keys) < len(columns):
        return "unusable"
    types = {c.name: column_type(c) for c in table.columns}
    prefix = [_key(key, types, confirmed_version) for key in index.keys[: len(columns)]]
    names = [name for name, _ in prefix]
    if len(set(columns)) != len(columns) or set(names) != set(columns):
        return "unusable"
    if (
        not all(plain for _, plain in prefix)
        or index.method != "btree"
        or index.predicate is not None
        or not set(columns) <= set(index.columns)
        or index.included_columns is None
    ):
        return "unknown"
    return "proven"


def evaluate(context: RuleContext) -> list[Finding]:
    result: list[Finding] = []
    for table in sorted(context.after.tables, key=lambda t: (t.schema_name, t.name)):
        for constraint in sorted(table.constraints, key=lambda c: c.name):
            if constraint.kind != "foreign_key":
                continue
            columns = constraint.columns
            states = (
                [
                    _coverage(index, columns, table, context.confirmed_version)
                    for index in table.indexes
                ]
                if columns
                else ["unknown"]
            )
            if "proven" in states and set(columns) <= {c.name for c in table.columns}:
                continue
            result.append(
                finding(
                    METADATA,
                    table.schema_name,
                    table.name,
                    constraint.name,
                    "foreign_key_index_unproven",
                    "low" if "unknown" in states else "high",
                    (
                        Evidence(
                            source="snapshot", detail=f"Referencing FK columns: {tuple(columns)!r}."
                        ),
                        Evidence(
                            source="snapshot",
                            detail="No valid complete plain btree key prefix proved coverage.",
                        ),
                    ),
                    (
                        "INCLUDE columns are not keys; partial/custom/legacy coverage is unproven.",
                        "Key permutation and expressions after a complete prefix are allowed.",
                        "Table-size modifiers and index-build locking policy belong to M4.",
                    ),
                )
            )
    return result
