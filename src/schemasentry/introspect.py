"""Snapshot collection: connect, choose a dialect, capture.

The CLI never touches psycopg directly, and the dialect never decides how to
connect. That separation is what lets the comparison engine run without a
database at all.
"""

from __future__ import annotations

from collections.abc import Sequence

import psycopg

from schemasentry.config import resolve_captured_at
from schemasentry.db import connect_readonly
from schemasentry.dialects import load_dialect
from schemasentry.errors import ToolError
from schemasentry.snapshot import Snapshot

DEFAULT_DIALECT = "postgres"


def capture_snapshot(
    dsn: str,
    *,
    schemas: Sequence[str] = (),
    captured_at: str | None = None,
    dialect: str = DEFAULT_DIALECT,
) -> Snapshot:
    """Capture one schema snapshot from a live database."""
    resolved_at = resolve_captured_at(captured_at)
    selected_dialect = load_dialect(dialect)

    try:
        with connect_readonly(dsn) as connection:
            return selected_dialect.capture(
                connection,
                schemas=schemas,
                captured_at=resolved_at,
            )
    except psycopg.Error as exc:
        # Query-level failures: permission denied, timeout, cancelled statement.
        raise ToolError(f"catalog query failed: {str(exc).strip()}") from None
