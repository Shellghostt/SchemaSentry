"""Run options resolved from flags and the environment.

No configuration file exists: a CI gate is a command line in a workflow, not a
hidden file that behaves differently on a laptop.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime

DATABASE_URL_ENV = "SCHEMASENTRY_DATABASE_URL"
SOURCE_DATE_EPOCH_ENV = "SOURCE_DATE_EPOCH"

CAPTURED_AT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def resolve_captured_at(
    value: str | None,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> str:
    """Return a UTC timestamp for `capturedAt`.

    `--captured-at` wins, then `SOURCE_DATE_EPOCH` (the reproducible-builds
    convention), then the clock. Without this, two snapshots of an unchanged
    database could never be byte-identical.
    """
    variables = os.environ if environ is None else environ

    if value is not None:
        return _parse(value)

    epoch = variables.get(SOURCE_DATE_EPOCH_ENV)
    if epoch:
        try:
            seconds = int(epoch)
        except ValueError as exc:
            raise ValueError(f"{SOURCE_DATE_EPOCH_ENV} must be an integer, got {epoch!r}") from exc
        return datetime.fromtimestamp(seconds, tz=UTC).strftime(CAPTURED_AT_FORMAT)

    current = now if now is not None else datetime.now(tz=UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).strftime(CAPTURED_AT_FORMAT)


def _parse(value: str) -> str:
    text = value.strip()
    if not text:
        raise ValueError("captured at must not be empty")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(
            f"captured at {value!r} is not an ISO 8601 timestamp; expected 2026-11-13T10:00:00Z"
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime(CAPTURED_AT_FORMAT)


def redact_dsn_error(message: str, dsn: str) -> str:
    """Remove a password from a connection error before it is printed.

    psycopg does not normally echo the password, but a driver error is not a
    good place to trust. The DSN is parsed rather than pattern-matched.
    """
    from psycopg.conninfo import conninfo_to_dict

    try:
        parameters = conninfo_to_dict(dsn)
    except Exception:
        # An unparseable DSN must not hide the real error.
        return message

    password = parameters.get("password")
    if isinstance(password, str) and password:
        return message.replace(password, "***")
    return message
