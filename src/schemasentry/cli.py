"""Command line interface for SchemaSentry.

Status: skeleton. Only `version` works. The plan lives in docs/PLAN.md.
"""

from __future__ import annotations

import typer

from schemasentry import __version__

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Detect dangerous database schema changes before they reach production.",
)


@app.command()
def version() -> None:
    """Print the installed version."""
    typer.echo(f"schemasentry {__version__}")


@app.callback()
def main() -> None:
    """SchemaSentry: Detect dangerous database schema changes before they reach production."""


if __name__ == "__main__":  # pragma: no cover
    app()
