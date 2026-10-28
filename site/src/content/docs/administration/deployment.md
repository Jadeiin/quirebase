---
title: Deploy Quirebase
description: Run the web application and durable worker with persistent storage.
---

Quirebase requires a web process, a separate durable worker, a database, and shared object storage.
Release wheels include the browser application and its PDFium asset. SQLite suits a single-host
installation with one worker; PostgreSQL is recommended for teams and multiple workers.

## Install a release wheel

Install Python 3.12+ and uv, then run these commands from a persistent installation directory:

```sh
uv tool install quirebase
quirebase init-db
quirebase create-admin
quirebase doctor
quirebase serve
```

In another terminal, with the same directory and configuration:

```sh
quirebase worker
```

Open `http://127.0.0.1:9060` and sign in with the administrator you created.
Keep both processes running. Defaults use `./quirebase.db` and `./quirebase-data`, so choose a stable
working directory or set explicit paths. Use a process supervisor for unattended operation.

For PostgreSQL, install `quirebase[postgres]` instead and set `QUIREBASE_DATABASE_URL` to a libpq URL
such as `postgresql://quirebase:password@localhost/quirebase` before initializing. SQLAlchemy driver
URLs such as `postgresql+psycopg://` are rejected.

## Run the Compose deployment

From a source checkout with Docker Compose or Podman Compose and Make available:

```sh
make docker-env
```

Edit `.env.docker` for the intended hostname, origin, storage, and Provider settings, then run:

```sh
make docker-up
make docker-admin
make docker-doctor
```

The stack includes PostgreSQL, migration initialization, web, and worker services, with persistent
database and object volumes. The published web port binds to loopback by default. `make docker-up-s3`
adds a single-node Garage service; follow the storage and backup limitations in the detailed
[operations guide](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#object-storage).

## Configure public access

Terminate TLS at a reverse proxy. Before exposing the application, set:

```dotenv
QUIREBASE_ALLOWED_HOSTS=library.example.org
QUIREBASE_EXTERNAL_ORIGIN=https://library.example.org
QUIREBASE_SECURE_COOKIES=true
```

Replace the example hostname with your deployment's address. The external origin includes the
scheme and any non-default port. Browser mutations validate that Origin. Configure request-size
limits at the proxy consistently with your upload settings.

Web and every worker must use the same database and object backend. Each worker needs its own stable
executor ID; retain that identity across restarts for automatic durable recovery. Do not scale the
bundled Compose worker under a shared identity.

Continue with [configuration](/administration/configuration/) and
[backup and upgrades](/administration/maintenance/). For a development checkout, follow
[contributing](/developers/contributing/).
