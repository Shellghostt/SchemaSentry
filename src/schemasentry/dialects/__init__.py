"""Dialect selection.

There is one implementation in M1. The lookup exists so that MySQL is additive
rather than a fork (PLAN section 5, decision 4).
"""

from __future__ import annotations

from schemasentry.dialects.base import Dialect
from schemasentry.dialects.postgres import PostgresDialect
from schemasentry.errors import ToolError


def load_dialect(name: str) -> Dialect:
    """Return the dialect for `name`, or fail with a tool error."""
    if name == "postgres":
        return PostgresDialect()
    raise ToolError(f"unsupported dialect {name!r}; supported: postgres")
