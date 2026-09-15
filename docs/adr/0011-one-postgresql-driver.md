# ADR 0011: One PostgreSQL driver behind one libpq URL

Status: accepted. Refines the PostgreSQL driver note in
[ADR 0006](0006-async-runtime-and-persistence.md).

## Context

Quirebase is asynchronous end to end, and the first PostgreSQL configuration accepted both
SQLAlchemy driver groups (`postgresql-psycopgbinary` and `postgresql-asyncpg`) plus several URL
spellings, including asyncpg-only query options that had to be translated or rejected before
connecting. The durable workflow engine (DBOS) already requires psycopg, and `pg_dump` and
`pg_restore` only accept libpq URLs, so the asyncpg path existed only as a second vocabulary to
keep in sync. Asynchronous database access does not require asyncpg: psycopg's native async
implementation is the driver the application, the durable workflows and the maintenance tooling
already share.

## Decision

`QUIREBASE_DATABASE_URL` is a libpq URL (`postgresql://` or the `postgres://` alias) or a SQLite
URL. The database module maps it to psycopg's native async implementation in one prefix step,
`pg_dump` and `pg_restore` receive the configured URL unchanged, and driver-suffixed spellings
such as `postgresql+asyncpg://` are configuration errors. The `postgres` extra installs
`postgresql-psycopgbinary` only.

## Consequences

One driver, one URL vocabulary and no option-translation layer between the application and the
maintenance tooling. A future, measured need for another driver is a new decision backed by
benchmark evidence; the configuration surface stays libpq-based so backups and restores keep
working.
