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
recommendations, object existence/sizes, and Workspace/Project integrity. The administrator
Maintenance page shows cleanup and workflow state.

## Back up and restore local object storage

Stop **all web and worker writers** before backing up so the database and objects can be copied
consistently. Keep archives outside data directories and replaceable volumes, with a unique
filename for each backup.

`verify-backup` checks the database payload's SHA-256 against the manifest and rejects unsafe archive
paths. It does not verify the content integrity of individual object files. Test restoration on a
separate installation as well.

### Source checkout: create and verify

Stop the web and worker processes, then run from the installation directory. Each run creates a
unique directory outside the installation and prints the archive path. The subshell stops on an
error:

```sh
(
  set -eu
  backup_dir=$(mktemp -d "../quirebase-backup-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
  backup_archive="$backup_dir/$(basename "$backup_dir").zip"
  printf 'Archive: %s\n' "$backup_archive"
  uv run quirebase backup "$backup_archive"
  uv run quirebase verify-backup "$backup_archive"
)
```

**Check the result:** both commands finish successfully and the archive exists at the chosen path.
It contains a SQLite snapshot or PostgreSQL dump, local immutable objects, and a database checksum
manifest. If either command fails, leave writers stopped and inspect the printed archive path and
diagnostics before retrying.
Restart web and worker after successful backup, and retain an independent off-host copy.

### Compose: copy the verified archive out of the container

Stop any additional workers first. Keep PostgreSQL running. From the checkout, the script below
stops the default web/worker services and uses a unique directory and archive name for each backup.
The parentheses run it in a subshell; `set -eu` stops it on an error even when pasted into an
interactive shell.

This example uses Docker. For Podman, replace `docker compose` with `podman compose` (or
`podman-compose` for a standalone provider), and `docker cp` / `docker rm` with `podman cp` /
`podman rm`. See [container engine selection](/administration/deployment/#container-engine-selection)
for the Makefile commands.

```sh
(
  set -eu
  mkdir -p backups
  backup_dir=$(mktemp -d "./backups/quirebase-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
  backup_container=$(basename "$backup_dir")
  backup_archive="$backup_dir/$backup_container.zip"
  printf 'Container: %s\nArchive: %s\n' "$backup_container" "$backup_archive"

  docker compose --env-file .env.docker stop web worker
  docker compose --env-file .env.docker run --name "$backup_container" --no-deps web sh -c 'quirebase backup /tmp/quirebase.zip && quirebase verify-backup /tmp/quirebase.zip'
  docker cp "$backup_container:/tmp/quirebase.zip" "$backup_archive"
  docker rm "$backup_container"
  docker compose --env-file .env.docker start web worker
)
```

The container is removed and writers restarted only after verification and copying succeed.
If backup, verification, or copying fails, the script leaves the backup container in place and
writers stopped. Use the printed container name and archive path to investigate; a failed copy may
leave an incomplete host file. Resolve the failure and successfully verify/copy the archive before
manually removing that container and starting web/worker. Keep a verified copy off the installation
host.

### Restore and validate

Test restoration on a separate installation first. Stop its writers, point it at the intended target
database and local object directory, and verify the archive. For a source target, set `backup_archive`
to the exact path printed by the backup script or another archive you have selected:

```sh
backup_archive=/absolute/path/to/selected-backup.zip
uv run quirebase verify-backup "$backup_archive"
uv run quirebase restore "$backup_archive" --force
uv run quirebase doctor
uv run quirebase reindex
```

`--force` replaces the configured database and restores archived objects. Inspect the target settings
before running it. For Compose, stop web and worker, use the same image/settings/volumes in a
one-off service, and make the archive accessible there. Restart web and
workers only after checks pass. Confirm sign-in, representative Items, file reads, and saved marks.

The `backup` command above works with local object storage. S3 installations need database and
object-store backups. For the bundled Garage setup, follow the
[snapshot procedure](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#object-storage).

## Upgrade an installation

1. Read the target release's database and durable-workflow instructions.
2. Stop every web/worker process and create/verify a backup outside replaceable volumes.
3. Install matching Quirebase, Inquiro, and Excerpo versions. For source, rebuild the frontend with
   that checkout's dependencies; for Compose, build or select the intended image.
4. Run the target version's `quirebase init-db` with the existing installation settings.
5. Run Doctor, restart web/worker, then repeat a sign-in and file-processing check.

Follow the target release's [upgrade instructions](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#upgrades)
for database and durable-workflow changes. To roll back, install the version matching your backup
and restore that backup.

## Recover durable work

Restart with the same stable executor ID to recover that worker's in-flight jobs. If an executor is
permanently retired, inspect before applying recovery:

```sh
uv run quirebase recover-workflows OLD_EXECUTOR_ID
uv run quirebase recover-workflows OLD_EXECUTOR_ID --apply
```

Replace `OLD_EXECUTOR_ID` with the retired identity. Give each running worker its own stable ID.
Tasks can be recovered within the workflow history retention period.

## Retention and database space

| Setting | Default | What it controls |
| --- | --- | --- |
| `QUIREBASE_ANNOTATION_UNDO_HOURS` | 24 hours | Ordinary Annotation/Reply undo window |
| `QUIREBASE_WORKFLOW_HISTORY_RETENTION_DAYS` | 7 days | Completed workflow history |
| `QUIREBASE_TERMINAL_METADATA_RETENTION_DAYS` | 30 days | Terminal credential/invitation/membership metadata |
| `QUIREBASE_AUDIT_RETENTION_DAYS` | 90 days | Retained Audit Events |
| `QUIREBASE_IMPORT_BATCH_RETENTION_DAYS` | 7 days | Temporary Import Batch history |

Import history expiration preserves committed Items and files but ends receipt replay and batch
filtering. Cleanup releases reusable database space. To shrink a SQLite file, stop all writers and
run `quirebase compact-sqlite`; PostgreSQL space maintenance is separate.
