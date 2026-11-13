"""Timestamp resolution and DSN redaction."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from schemasentry.config import redact_dsn_error, resolve_captured_at


def test_explicit_timestamp_is_used_verbatim() -> None:
    assert resolve_captured_at("2026-11-13T10:00:00Z") == "2026-11-13T10:00:00Z"


def test_explicit_offset_is_converted_to_utc() -> None:
    assert resolve_captured_at("2026-11-13T12:30:00+02:30") == "2026-11-13T10:00:00Z"


def test_naive_timestamp_is_treated_as_utc() -> None:
    assert resolve_captured_at("2026-11-13T10:00:00") == "2026-11-13T10:00:00Z"


SOURCE_DATE = datetime(2026, 11, 13, 10, tzinfo=UTC)
SOURCE_DATE_EPOCH = str(int(SOURCE_DATE.timestamp()))


def test_source_date_epoch_is_honoured() -> None:
    assert resolve_captured_at(None, environ={"SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH}) == (
        "2026-11-13T10:00:00Z"
    )


def test_explicit_timestamp_beats_source_date_epoch() -> None:
    assert (
        resolve_captured_at(
            "2026-01-02T03:04:05Z", environ={"SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH}
        )
        == "2026-01-02T03:04:05Z"
    )


def test_clock_is_used_as_the_last_resort() -> None:
    moment = datetime(2026, 11, 13, 12, 0, tzinfo=timezone(timedelta(hours=2)))

    assert resolve_captured_at(None, environ={}, now=moment) == "2026-11-13T10:00:00Z"


def test_naive_clock_is_treated_as_utc() -> None:
    assert resolve_captured_at(None, environ={}, now=datetime(2026, 11, 13, 10)) == (
        "2026-11-13T10:00:00Z"
    )


@pytest.mark.parametrize("value", ["", "   ", "yesterday", "2026-13-01T00:00:00Z"])
def test_invalid_timestamp_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        resolve_captured_at(value)


def test_invalid_source_date_epoch_is_rejected() -> None:
    with pytest.raises(ValueError):
        resolve_captured_at(None, environ={"SOURCE_DATE_EPOCH": "soon"})


def test_password_is_removed_from_an_error_message() -> None:
    dsn = "postgresql://app:s3cret@db.example.com:5432/app"
    message = "connection failed for postgresql://app:s3cret@db.example.com:5432/app"

    cleaned = redact_dsn_error(message, dsn)

    assert "s3cret" not in cleaned
    assert "***" in cleaned


def test_message_without_a_password_is_unchanged() -> None:
    dsn = "postgresql://app@db.example.com/app"

    assert redact_dsn_error("timeout", dsn) == "timeout"


def test_unparseable_dsn_does_not_hide_the_error() -> None:
    assert redact_dsn_error("boom", "://not a dsn") == "boom"


def test_utc_constant_is_used_for_epoch() -> None:
    # Pinned so a change from UTC to local time fails here rather than producing
    # different bytes on different machines.
    expected = datetime.fromtimestamp(int(SOURCE_DATE_EPOCH), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert resolve_captured_at(None, environ={"SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH}) == expected
