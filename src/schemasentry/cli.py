"""Command line interface for SchemaSentry.

Exit codes are public API (PLAN section 8):

    0  nothing at or above the threshold
    1  threshold crossed
    2  blocking risk
    3  tool error (connection, parse, unsupported dialect)
    4  invalid usage

M2 implements `snapshot`, structural `diff`, and `version`. Risk analysis is later work.
"""

import io
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import typer

from schemasentry import __version__
from schemasentry.config import DATABASE_URL_ENV, resolve_captured_at
from schemasentry.diff import compare, comparison_json, load_snapshot
from schemasentry.errors import EXIT_OK, EXIT_TOOL_FAILURE, EXIT_USAGE, ToolError
from schemasentry.introspect import capture_snapshot
from schemasentry.snapshot import to_json, write_snapshot

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Detect dangerous database schema changes before they reach production.",
)


@app.command()
def snapshot(
    database: Annotated[
        str | None,
        typer.Option(
            "--database",
            "-d",
            envvar=DATABASE_URL_ENV,
            help="PostgreSQL connection URL. Defaults to $SCHEMASENTRY_DATABASE_URL.",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Write the snapshot here instead of stdout."),
    ] = None,
    schema: Annotated[
        list[str] | None,
        typer.Option(
            "--schema",
            help="Schema to capture. Repeatable. Defaults to every non-system schema.",
        ),
    ] = None,
    captured_at: Annotated[
        str | None,
        typer.Option(
            "--captured-at",
            help="ISO 8601 timestamp for capturedAt, for reproducible output.",
        ),
    ] = None,
) -> None:
    """Capture a read-only, deterministic snapshot of a PostgreSQL schema."""
    if database is None:
        typer.echo(
            f"error: no database URL; pass --database or set {DATABASE_URL_ENV}",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE)

    try:
        timestamp = resolve_captured_at(captured_at)
    except ValueError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_USAGE) from None

    try:
        document = capture_snapshot(
            database,
            schemas=tuple(schema or ()),
            captured_at=timestamp,
        )
        if output is None:
            typer.echo(to_json(document), nl=False)
        else:
            write_snapshot(output, document)
            typer.echo(
                f"wrote snapshot: {len(document.tables)} tables, "
                f"{len(document.sequences)} sequences -> {output}",
                err=True,
            )
    except (ToolError, OSError) as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_TOOL_FAILURE) from None


@app.command()
def diff(
    before: Annotated[Path, typer.Option("--before", help="Baseline snapshot file.")],
    after: Annotated[Path, typer.Option("--after", help="Resulting snapshot file.")],
) -> None:
    """Print structural changes as JSON. M2 does not classify migration risk."""
    try:
        result = compare(load_snapshot(before), load_snapshot(after))
        typer.echo(comparison_json(result), nl=False)
    except ToolError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(EXIT_TOOL_FAILURE) from None


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(f"schemasentry {__version__}")


@app.callback()
def main_callback() -> None:
    """SchemaSentry: Detect dangerous database schema changes before they reach production."""


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code.

    The command framework exits the process for `--help`, a usage error and an
    explicit `typer.Exit`. Catch that boundary so tests can assert the code,
    and translate the framework's usage code (2) into the documented code (4).
    """
    try:
        app(args=list(argv) if argv is not None else None)
    except SystemExit as exc:
        code = exc.code
        if not isinstance(code, int):
            return EXIT_TOOL_FAILURE
        return EXIT_USAGE if code == 2 else code
    return EXIT_OK


def run() -> None:
    """Console-script entry point."""
    # Keep JSON bytes UTF-8/LF when redirected, including Windows pipes.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.exit(main())


if __name__ == "__main__":  # pragma: no cover
    run()
