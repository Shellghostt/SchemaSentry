"""Read-only database access.

Every catalog query runs inside a read-only transaction with a statement
timeout. That is the enforcement of the threat-model row "tool writes to the
database": the tool cannot write even if a future query tried to.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row

from schemasentry.config import redact_dsn_error
from schemasentry.errors import ToolError

CONNECT_TIMEOUT_SECONDS = 10
STATEMENT_TIMEOUT = "5s"


@contextmanager
def connect_readonly(dsn: str) -> Iterator[Connection[dict[str, Any]]]:
    """Open a connection that can only read, with a 5 s statement timeout."""
    try:
        connection = psycopg.connect(
            dsn,
            connect_timeout=CONNECT_TIMEOUT_SECONDS,
            application_name="schemasentry",
            row_factory=dict_row,
        )
    except psycopg.Error as exc:
        message = redact_dsn_error(str(exc).strip(), dsn)
        raise ToolError(f"could not connect to the database: {message}") from None

    try:
        connection.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        connection.read_only = True
        with connection.transaction():
            # SET does not accept a bind parameter; the value is a constant in
            # this module and never comes from the command line.
            connection.execute(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'")
            yield connection
    finally:
        connection.close()
