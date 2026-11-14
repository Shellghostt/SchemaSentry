# SchemaSentry M1/M2 validation — 2026-11-14

Branch: `feat/m2-implementation`, pushed for remote validation. M2 remains unreleased; main is unchanged.

M2 covers structural table/column/constraint/index changes, deterministic sorting, ignored physical
column order/statistics and unchanged constraint/index renames. Thirty fixture pairs exceed the
20-pair requirement. Thirty real CLI subprocess cases check exact UTF-8/LF bytes, exit 0 and the
committed diff JSON schema. Snapshot loading rejects duplicate fields/objects, non-integer or unknown
versions, unknown fields and wrong dialects, with a 64 MiB input cap.

Native Python 3.12.10 full suite: **122 passed**, 96% statement coverage. Ruff lint/format and strict
mypy checks passed. Fifteen live
integration tests passed on each of PostgreSQL 13, 15 and 16.16. They verify read-only REPEATABLE READ
capture, five-second statement timeout, M1 schema/determinism contracts, live rename suppression and
changed CHECK/index ordering detection. A new live test exposed missing index ordering flags in the
column form of `pg_get_indexdef`; the catalog reader now includes direction/null ordering/collation/opclass.
Boolean/float schema-version acceptance, duplicate JSON fields and Windows pipe newline translation
were also reproduced with failing tests before being fixed.

The 500-table comparison took **0.036836 seconds**, below the 10-second acceptance limit, on this
Windows host. This is a local observation, not a large-production-schema benchmark. Wheel and source
distribution builds passed. The non-root Docker runtime built with hashed dependencies and ran a
column-removal diff with `--network none`. `pip-audit --disable-pip --require-hashes -r requirements.lock`
found no known vulnerabilities. CI now installs/audits the actual locked runtime dependencies and
triggers on feature/fix branches. The [remote M2 CI run](https://github.com/Shellghostt/SchemaSentry/actions/runs/43550178853)
passed all six jobs at `ad1406c`: Python 3.12/3.13 tests, lint, format and type checks; integration on
PostgreSQL 13/15/16; and the locked dependency audit.

```powershell
$env:SCHEMASENTRY_TEST_DATABASE_URL='postgresql://schemasentry:schemasentry@127.0.0.1:55437/schemasentry'
.venv/Scripts/python -m pytest --cov=src --cov-report=term-missing
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m ruff format --check .
.venv/Scripts/python -m mypy src
uv build
uvx pip-audit --disable-pip --require-hashes -r requirements.lock
```

Use a disposable server for integration tests. Test-only DDL creates and removes a temporary schema;
the product's capture path is read-only. Windows tests use explicit IPv4 loopback because `localhost`
first tried the unbound IPv6 Docker endpoint. Setup connections now also have a ten-second deadline.
Task test servers are stopped after validation, preserving the older containers and their data.

M2 has no risk verdicts: changed snapshots still exit 0. Sequences/extensions, capture-scope differences,
uncaptured table properties and SQL-expression equivalence across server versions are not compared.
Use the same collector and matching capture scope; recapture legacy snapshots to remove evidence warnings.
