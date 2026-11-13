"""Exit codes and error types for SchemaSentry.

Exit codes are public API: CI depends on them, so changing one is a breaking
change (PLAN section 8).
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_THRESHOLD = 1
EXIT_BLOCKING = 2
EXIT_TOOL_FAILURE = 3
EXIT_USAGE = 4


class ToolError(Exception):
    """A failure of the tool itself: connection, parse or unsupported dialect.

    Maps to exit code 3. It never means the analysed migration is dangerous;
    that is a finding, not an error.
    """
