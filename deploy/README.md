# Deployment and local infrastructure

SchemaSentry is a CLI and a CI gate, not a service. There is nothing to deploy.

## Local PostgreSQL

`deploy/docker-compose.yml` starts a disposable PostgreSQL 16 for development and integration tests:

```bash
make db-up      # docker compose -f deploy/docker-compose.yml up -d postgres
make db-down    # stops it and removes the volume
```

Connection details: host `localhost`, port `55432`, user `schemasentry`, password `schemasentry`,
database `schemasentry`.

```bash
export SCHEMASENTRY_DATABASE_URL="postgresql://schemasentry:schemasentry@localhost:55432/schemasentry"
schemasentry snapshot --output snapshot.json
```

The compose file also defines a `cli` service behind the `cli` profile for running the tool inside
the compose network. It is not used by the test suite.

## Container image

`Dockerfile` builds a slim image that runs the CLI. It exists for CI and for trying the tool out, not
as a product: SchemaSentry inspects a database over the network and never needs to run beside the
database it inspects.

```bash
make docker
docker run --rm -e SCHEMASENTRY_DATABASE_URL="$SCHEMASENTRY_DATABASE_URL" schemasentry:latest snapshot
```

The image has no database credentials baked in and no write access of its own.

## Secrets

The connection URL is read from `SCHEMASENTRY_DATABASE_URL` by default so it does not appear in a CI
log as a command-line argument. If a connection error is printed, the password is redacted first.
Snapshots contain the database name but never the host, the user or the password.

## Releases

Publishing to PyPI is planned for M5, together with the GitHub Action. Nothing is published yet, and
no installation instructions claim otherwise.
