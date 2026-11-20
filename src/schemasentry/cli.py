"""Command line interface for SchemaSentry.

Exit codes are public API (PLAN section 8):

    0  nothing at or above the threshold
    1  threshold crossed
    2  blocking risk
    3  tool error (connection, parse, unsupported dialect)
    4  invalid usage

M4 adds observed-state `compare`, `rules`, and `explain`; structural `diff` stays unchanged.
"""

import io
import json
import os
import sys
from collections.abc import Sequence
from importlib import import_module
from pathlib import Path
from typing import Annotated, Protocol, cast

import typer

from schemasentry import __version__
from schemasentry.assessment import LEVELS, assess, report_exit
from schemasentry.config import DATABASE_URL_ENV, resolve_captured_at
from schemasentry.diff import compare, comparison_json, load_snapshot
from schemasentry.errors import EXIT_OK, EXIT_TOOL_FAILURE, EXIT_USAGE, ToolError
from schemasentry.hints import load_hints
from schemasentry.introspect import capture_snapshot
from schemasentry.m4_migration import load_assessment_migration
from schemasentry.registry import public_rules
from schemasentry.report import report_json, report_markdown
from schemasentry.report_io import check_output, publish_report, write_checked
from schemasentry.snapshot import to_json, write_snapshot


class _FrameworkDisplay(Protocol):
    def show(self) -> None: ...


def _framework_errors() -> tuple[type[Exception], type[Exception]]:
    # Typer 0.29 vendors Click; older supported Typer versions use the Click package.
    try:
        module = import_module("typer._click.exceptions")
    except ModuleNotFoundError:
        module = import_module("click.exceptions")
    return cast(type[Exception], module.ClickException), cast(type[Exception], module.UsageError)


Abort = typer.Abort
ClickException, UsageError = _framework_errors()

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
    analysis_evidence: Annotated[
        bool,
        typer.Option(
            "--analysis-evidence",
            help="Include optional M4 enum/constraint/dependency catalog evidence.",
        ),
    ] = False,
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
        if analysis_evidence:
            document = capture_snapshot(
                database, schemas=tuple(schema or ()), captured_at=timestamp, analysis_evidence=True
            )
        else:
            document = capture_snapshot(
                database, schemas=tuple(schema or ()), captured_at=timestamp
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


@app.command("compare")
def assess_command(
    baseline: Annotated[
        Path,
        typer.Option(
            "--baseline",
            help="Before snapshot; use --analysis-evidence when capturing M4 baselines.",
        ),
    ],
    after: Annotated[
        Path | None,
        typer.Option(
            "--after",
            help="Observed after snapshot; fully offline and ignores a database environment URL.",
        ),
    ] = None,
    database: Annotated[
        str | None,
        typer.Option(
            "--database",
            "-d",
            help=(
                "Read-only observed after-state URL; environment fallback applies "
                "only without --after."
            ),
        ),
    ] = None,
    migration: Annotated[
        Path | None,
        typer.Option(
            "--migration",
            help="One bounded SQL evidence file; never executed or used to predict an after state.",
        ),
    ] = None,
    hints: Annotated[
        Path | None, typer.Option("--hints", help="Bounded rename-hints v1 file.")
    ] = None,
    default_schema: Annotated[
        str,
        typer.Option("--default-schema", help="Explicit binding for unqualified SQL identifiers."),
    ] = "public",
    format: Annotated[str, typer.Option("--format", help="markdown or json.")] = "markdown",
    threshold: Annotated[
        str,
        typer.Option(
            "--threshold", help="low, medium, high or critical; critical risk always returns 2."
        ),
    ] = "high",
    output: Annotated[
        Path | None,
        typer.Option(
            "--output", "-o", help="Atomically publish a complete report instead of stdout."
        ),
    ] = None,
    captured_at: Annotated[
        str | None,
        typer.Option(
            "--captured-at", help="Reproducible live-capture timestamp; incompatible with --after."
        ),
    ] = None,
) -> None:
    """Assess supplied/observed states, without applying SQL or predicting a migration."""
    if format not in ("markdown", "json") or threshold not in LEVELS or not default_schema:
        typer.echo("error: invalid assessment format, threshold or default schema", err=True)
        raise typer.Exit(EXIT_USAGE)
    if after is not None and (database is not None or captured_at is not None):
        typer.echo("error: --after conflicts with explicit live-capture arguments", err=True)
        raise typer.Exit(EXIT_USAGE)
    live = (
        (database if database is not None else os.environ.get(DATABASE_URL_ENV))
        if after is None
        else None
    )
    if after is None and not live:
        typer.echo("error: choose --after or supply a live database URL", err=True)
        raise typer.Exit(EXIT_USAGE)
    timestamp = None
    if captured_at is not None:
        try:
            timestamp = resolve_captured_at(captured_at)
        except ValueError:
            typer.echo("error: invalid live captured-at timestamp", err=True)
            raise typer.Exit(EXIT_USAGE) from None
    selected = [baseline, *(path for path in (after, migration, hints) if path is not None)]
    try:
        check_output(output, selected)
        before_document = load_snapshot(baseline)
        if after is not None:
            after_document = load_snapshot(after)
        else:
            assert live is not None
            after_document = capture_snapshot(
                live, schemas=before_document.schemas, captured_at=timestamp, analysis_evidence=True
            )
        assessment_migration = (
            load_assessment_migration(migration) if migration is not None else None
        )
        rename_hints = load_hints(hints) if hints is not None else None
        result = assess(
            before_document,
            after_document,
            migration=assessment_migration,
            hints=rename_hints,
            default_schema=default_schema,
            threshold=threshold,
        )
        text = report_json(result) if format == "json" else report_markdown(result)
        if output is None:
            write_checked(sys.stdout, text)
        else:
            publish_report(output, text, selected)
    except Exception:
        typer.echo("error: cannot complete or publish assessment", err=True)
        raise typer.Exit(EXIT_TOOL_FAILURE) from None
    raise typer.Exit(report_exit(result))


@app.command("rules")
def rules_command(
    json_output: Annotated[
        bool, typer.Option("--json", help="Versioned public registry JSON.")
    ] = False,
) -> None:
    """List all ten rule definitions offline; no capture or connection occurs."""
    try:
        definitions = public_rules()
        text = (
            json.dumps(
                {
                    "schemaVersion": 1,
                    "rules": [rule.model_dump(by_alias=True, mode="json") for rule in definitions],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
            if json_output
            else "".join(
                f"{rule.rule_id}: {rule.title} [{rule.base_severity}]\n" for rule in definitions
            )
        )
        write_checked(sys.stdout, text)
    except Exception:
        typer.echo("error: cannot write rule metadata", err=True)
        raise typer.Exit(EXIT_TOOL_FAILURE) from None


@app.command("explain")
def explain_command(rule_id: str) -> None:
    """Explain a public rule offline, with references and evidence limitations."""
    rule = next((rule for rule in public_rules() if rule.rule_id == rule_id.upper()), None)
    if rule is None:
        typer.echo("error: unknown rule ID", err=True)
        raise typer.Exit(EXIT_USAGE)
    text = (
        f"{rule.rule_id}: {rule.title}\nBase severity: {rule.base_severity}\n\n"
        f"{rule.description}\n\n"
        f"Alternative: {rule.safe_alternative or 'unavailable'}\n"
    )
    text += "".join(f"Limitation: {limitation}\n" for limitation in rule.limitations)
    text += "".join(f"Evidence: {item}\n" for item in rule.evidence_requirements)
    text += "".join(f"Reference: {reference}\n" for reference in rule.references)
    try:
        write_checked(sys.stdout, text)
    except Exception:
        typer.echo("error: cannot write rule explanation", err=True)
        raise typer.Exit(EXIT_TOOL_FAILURE) from None


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
        result = app(args=list(argv) if argv is not None else None, standalone_mode=False)
        return result if type(result) is int else EXIT_OK
    except UsageError as exc:
        cast(_FrameworkDisplay, exc).show()
        return EXIT_USAGE
    except ClickException as exc:
        cast(_FrameworkDisplay, exc).show()
        return EXIT_TOOL_FAILURE
    except (Abort, OSError, ValueError):
        return EXIT_TOOL_FAILURE
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
