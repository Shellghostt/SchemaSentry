"""Dialect contract.

A dialect owns the catalog queries and the type normalisation for one database
engine. The rest of the package never sees a catalog, only a Snapshot.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from psycopg import Connection

from schemasentry.snapshot import Snapshot


class Dialect(Protocol):
    """One database engine's introspection implementation."""

    name: str

    def capture(
        self,
        connection: Connection[dict[str, Any]],
        *,
        schemas: Sequence[str],
        captured_at: str,
    ) -> Snapshot:
        """Read the schema state. Must not modify anything."""
        ...
