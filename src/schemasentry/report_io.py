"""Checked output and atomic report publication without overwriting selected inputs."""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import TextIO

from schemasentry.errors import ToolError


def check_output(path: Path | None, inputs: Sequence[Path]) -> None:
    if path is None:
        return
    try:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ToolError("report destination must be a regular file")
        for selected in inputs:
            if path.resolve() == selected.resolve() or (
                path.exists() and selected.exists() and path.samefile(selected)
            ):
                raise ToolError("report destination is a selected input")
    except OSError:
        raise ToolError("cannot validate report destination") from None


def write_checked(handle: TextIO, text: str) -> None:
    try:
        if handle.write(text) != len(text):
            raise ToolError("short report write")
        handle.flush()
    except (OSError, ValueError):
        # Prevent Python's shutdown flush from replacing tool exit 3 with 120
        # after a broken/closed stdout. Other selected output files are untouched.
        if handle is sys.stdout:
            with suppress(OSError, ValueError, AttributeError):
                descriptor = os.open(os.devnull, os.O_WRONLY)
                target = handle.fileno()
                try:
                    os.dup2(descriptor, target)
                finally:
                    if descriptor != target:
                        os.close(descriptor)
        raise ToolError("cannot write complete report") from None


def publish_report(path: Path, text: str, inputs: Sequence[Path]) -> None:
    check_output(path, inputs)
    temporary: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            write_checked(handle, text)
            os.fsync(handle.fileno())
        check_output(path, inputs)
        os.replace(temporary, path)
    except BaseException:
        if temporary is not None:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
        raise
