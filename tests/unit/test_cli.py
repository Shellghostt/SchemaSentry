"""CLI contract: exit codes, stream separation, and no secret leakage."""

from __future__ import annotations

import pytest

from schemasentry.cli import main
from schemasentry.config import DATABASE_URL_ENV
from schemasentry.errors import EXIT_OK, EXIT_TOOL_FAILURE, EXIT_USAGE


def test_version_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == EXIT_OK

    captured = capsys.readouterr()
    assert captured.out == "schemasentry 0.1.0\n"
    assert captured.err == ""


def test_no_arguments_prints_help_and_counts_as_usage(capsys: pytest.CaptureFixture[str]) -> None:
    # The help text is shown, but running a CI gate with no command is still a
    # usage error, so the exit code is 4 rather than 0.
    assert main([]) == EXIT_USAGE

    captured = capsys.readouterr()
    assert "Usage:" in captured.out + captured.err


def test_unknown_command_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["nope"]) == EXIT_USAGE

    assert "No such command" in capsys.readouterr().err


def test_unknown_option_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["snapshot", "--nope"]) == EXIT_USAGE

    assert "No such option" in capsys.readouterr().err


def test_snapshot_without_a_database_url_is_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv(DATABASE_URL_ENV, raising=False)

    assert main(["snapshot"]) == EXIT_USAGE

    err = capsys.readouterr().err
    assert DATABASE_URL_ENV in err
    assert "--database" in err


def test_invalid_captured_at_is_rejected_before_connecting(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(
        [
            "snapshot",
            "--database",
            "postgresql://app@127.0.0.1:1/app",
            "--captured-at",
            "yesterday",
        ]
    )

    assert code == EXIT_USAGE
    assert "ISO 8601" in capsys.readouterr().err


def test_connection_failure_is_a_tool_error_without_the_password(
    capsys: pytest.CaptureFixture[str],
) -> None:
    dsn = "postgresql://app:s3cret@127.0.0.1:1/app"

    code = main(["snapshot", "--database", dsn])

    assert code == EXIT_TOOL_FAILURE
    err = capsys.readouterr().err
    assert "could not connect" in err
    assert "s3cret" not in err
