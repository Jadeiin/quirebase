---
title: Back up, upgrade, and recover
description: Stop the correct writers, create a verifiable offline backup, restore safely, and recover durable jobs.
---

Run commands with the installation's database, data directory, and object-store settings. The
examples for source checkouts use `uv run quirebase`; a release-wheel installation uses its
`quirebase` executable. Compose commands below refer to the default local-object-storage stack.

## Check health

For source, run `uv run quirebase doctor`; for Compose, run `make docker-doctor`. Exit status 0 and
`[ok]` diagnostics indicate the checks passed. A `[failed]` result needs investigation before an
upgrade or restart is considered complete.

Doctor checks database/schema access, workflow storage, writable directories, PDF support,
recommendations, object existence/sizes, and Workspace/Project integrity. It does not hash each
stored object. The administrator Maintenance page shows cleanup and workflow state.

## Back up and restore local object storage

A backup requires **all web and worker writers to be stopped**. The database and objects are copied
separately; stopping only one worker does not make a multi-worker installation offline. Keep the
archive outside data directories and volumes that may be recreated. Use a new filename for each
retained backup rather than replacing the only verified copy.

### Source checkout: create and verify

Stop the web and worker processes, then run from the installation directory:

```sh
uv run quirebase backup ../quirebase-backup.zip
uv run quirebase verify-backup ../quirebase-backup.zip
```

**Check the result:** both commands finish successfully and the archive exists at the chosen path.
It contains a SQLite snapshot or PostgreSQL dump, local immutable objects, and a database checksum
manifest. Verification checks the database checksum and archive paths, not every object's checksum.
Restart web and worker after successful backup, and retain an independent off-host copy.

### Compose: copy the verified archive out of the container

Stop the default web/worker services and any additional workers. Keep PostgreSQL running. From the
checkout, the following creates a stopped backup container long enough to copy out its archive:

```sh
mkdir -p backups
docker compose --env-file .env.docker stop web worker
docker compose --env-file .env.docker run --name quirebase-backup --no-deps web sh -c 'quirebase backup /tmp/quirebase.zip && quirebase verify-backup /tmp/quirebase.zip'
docker cp quirebase-backup:/tmp/quirebase.zip ./backups/quirebase.zip
docker rm quirebase-backup
docker compose --env-file .env.docker start web worker
```

Copy the archive successfully **before** removing the backup container. Resolve a backup error before
continuing. The example container name must be free when rerun, and the example destination should
be changed to a unique retained filename. Move a verified copy off the installation host.

### Restore and validate

Test restoration on a separate installation first. Stop its writers, point it at the intended target
database and local object directory, and verify the archive. For a source target:

```sh
uv run quirebase verify-backup ../quirebase-backup.zip
uv run quirebase restore ../quirebase-backup.zip --force
uv run quirebase doctor
uv run quirebase reindex
```

`--force` replaces the configured database and restores archived objects. Inspect the target settings
before running it. For Compose, use the same image/settings/volumes in a one-off service and make
the archive accessible there; do not run restore inside a still-serving web process. Restart web and
workers only after checks pass. Confirm sign-in, representative Items, file reads, and saved marks.

S3 storage needs its own backup/versioning policy: `quirebase backup` refuses non-local objects.
The bundled Garage variant has one node and no bucket versioning; follow its detailed
[snapshot procedure](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#object-storage).

## Upgrade an installation

1. Read the target release's database and durable-workflow instructions.
2. Stop every web/worker process and create/verify a backup outside replaceable volumes.
3. Install matching Quirebase, Inquiro, and Excerpo versions. For source, rebuild the frontend with
   that checkout's dependencies; for Compose, build or select the intended image.
4. Run the target version's `quirebase init-db` with the existing installation settings.
5. Run Doctor, restart web/worker, then repeat a sign-in and file-processing check.

Alpha releases may require database recreation and reimport. Persisted workflow formats are not
assumed compatible. Rolling back after a database change requires the matching backup, not just
older packages. See the detailed [upgrade transitions](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#upgrades),
including DBOS storage changes.

## Recover durable work

Restart with the same stable executor ID to recover that worker's in-flight jobs. If an executor is
permanently retired, inspect before applying recovery:

```sh
uv run quirebase recover-workflows OLD_EXECUTOR_ID
uv run quirebase recover-workflows OLD_EXECUTOR_ID --apply
```

Replace `OLD_EXECUTOR_ID` with the actual retired identity. Recovery is not a reason to give two live
workers the same ID. Retained workflow history eventually expires and then cannot be resumed.

## Retention and database space

| Setting | Default | What it controls |
| --- | --- | --- |
| `QUIREBASE_ANNOTATION_UNDO_HOURS` | 24 hours | Ordinary Annotation/Reply undo window |
| `QUIREBASE_WORKFLOW_HISTORY_RETENTION_DAYS` | 7 days | Completed workflow history |
| `QUIREBASE_TERMINAL_METADATA_RETENTION_DAYS` | 30 days | Terminal credential/invitation/membership metadata |
| `QUIREBASE_AUDIT_RETENTION_DAYS` | 90 days | Retained Audit Events |
| `QUIREBASE_IMPORT_BATCH_RETENTION_DAYS` | 7 days | Temporary Import Batch history |

Import history expiration preserves committed Items and files but ends receipt replay and batch
filtering. These settings do not create automatic content, account, or backup expiration.
Deleting rows may make space reusable without shrinking the database file. SQLite compaction needs
all writers stopped before `quirebase compact-sqlite`; PostgreSQL space maintenance is separate.
