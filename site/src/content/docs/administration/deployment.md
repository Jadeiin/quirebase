---
title: Deploy and verify Quirebase
description: Build a checkout, initialize persistent data, run web and worker, and verify the first login.
---

Choose one installation method below. Both run the current source checkout with locked dependencies.
For published release wheels, follow that release's package-index and version instructions.

| Method | Prerequisites | Processes and storage |
| --- | --- | --- |
| Compose | Git, Docker Compose or Podman Compose, Make, and OpenSSL | PostgreSQL, initialization, web, worker, and named data volumes |
| Source checkout | Git, Python 3.12+, uv 0.13.5+, and Bun 1.4.4 | You run web and worker separately; defaults use SQLite and local files |

The shell examples use Linux, macOS, or WSL. Use a persistent installation directory and keep the
same configuration for every process. The web process serves the application; the separate worker
processes PDFs and durable jobs.

## Option A: build and run the Compose stack

```sh
git clone https://github.com/Jadeiin/quirebase.git
cd quirebase
make docker-env
make docker-build
make docker-up
make docker-admin
make docker-doctor
```

`docker-env` creates `.env.docker` with a generated database password. Review that file before public
access. `docker-build` builds this checkout's image, including browser assets. `docker-up` starts
PostgreSQL, the one-shot migration service, web, and worker. `docker-admin` creates the initial
administrator and prompts for its password; the default username is `admin`.

Open `http://127.0.0.1:9060` and sign in with that administrator's credentials. Check service state
with `make docker-ps`. `make docker-doctor` should finish with exit status 0 and `[ok]` diagnostics.
For a stuck job, inspect worker logs:

```sh
docker compose --env-file .env.docker logs --tail 50 worker
```

The database uses the Compose `postgres-data` volume and local objects use `quirebase-data`.
`make docker-down` stops the stack while preserving those volumes. Volume deletion is a separate,
destructive action. The default published web port binds to loopback only.

## Option B: run a source checkout with SQLite

```sh
git clone https://github.com/Jadeiin/quirebase.git
cd quirebase
uv sync --frozen
bun install --cwd frontend --frozen-lockfile
bun run --cwd frontend build
uv run quirebase init-db
uv run quirebase create-admin
uv run quirebase doctor
```

`create-admin` prompts for a username and password. It does not install a shared demonstration
password. `init-db` creates/applies the database and workflow-storage schema; it is not a replacement
for a running worker.

In terminal 1, from the installation directory:

```sh
uv run quirebase serve
```

In terminal 2, from the **same directory** with the **same `.env` and environment**:

```sh
uv run quirebase worker
```

Open `http://127.0.0.1:9060`. Defaults create `./quirebase.db` and `./quirebase-data` in the working
directory. Do not put production data in a temporary checkout. For unattended operation, configure
supervised web and worker processes with these same paths and settings.

For PostgreSQL, create a database and credentials through your database service, run
`uv sync --frozen --extra postgres`, and set `QUIREBASE_DATABASE_URL` in `.env` before initialization.
Use a libpq URL such as `postgresql://quirebase:encoded-password@localhost/quirebase`.
SQLAlchemy driver spellings such as `postgresql+psycopg://` are unsupported.

## Verify the first end-to-end task

1. Sign in and open the administrator's ordinary Workspace.
2. [Create a reference and upload a PDF](/getting-started/quickstart/).
3. Confirm PDF processing reaches ready and the reader opens it.
4. Save a private note and reopen the same revision to check persistence.

A working sign-in page alone does not verify the worker or file store. If this task stalls, follow
[troubleshooting](/knowledge-base/troubleshooting/).

## Configure access through an HTTPS proxy

Before public use, terminate TLS at a reverse proxy and set the actual public address in `.env` or
`.env.docker`:

```dotenv
QUIREBASE_ALLOWED_HOSTS=library.example.org
QUIREBASE_EXTERNAL_ORIGIN=https://library.example.org
QUIREBASE_SECURE_COOKIES=true
```

Replace the example hostname. The external origin includes the scheme and any non-default port;
unsafe browser requests must match it. Coordinate proxy upload limits with the application's limits.
Restart source processes after deployment-setting changes; for Compose, apply them with
`make docker-up`.

Web and all workers must use the same database and object store. Give each additional worker a
unique, stable executor ID. The bundled Compose worker intentionally cannot be scaled with a shared
identity. Continue with [configuration](/administration/configuration/) and
[backups and upgrades](/administration/maintenance/).
