---
title: Back up, upgrade, and recover
description: Preserve data, run health checks, and operate durable workers.
---

## Check health

Run `quirebase doctor` with the installation's configuration. It checks database connectivity,
initialized tables, workflow storage, writable directories, PDF support, the Recommendation Engine,
object existence and sizes, and Workspace/Project integrity. It does not hash stored objects.

Use the administrator Maintenance page for cleanup results and workflow state. A running worker
performs hourly maintenance. `quirebase reindex` rebuilds Library Search after restoration or an
indexing-rule change.

## Back up and restore local object storage

Stop **every web and worker process** before creating or restoring a backup. Running writes or
cleanup can make the separate database and object copies inconsistent.

```sh
quirebase backup /path/outside-data/backup.zip
quirebase verify-backup /path/outside-data/backup.zip
```

The archive contains a SQLite snapshot or PostgreSQL dump, immutable local objects, and a database
checksum manifest. Verification checks the database checksum and archive paths, not individual
object checksums. Keep backups outside the installation's data directory and replaceable volumes.

Test restoration on a separate installation. To replace its configured database and overlay the
backed-up objects, with its processes stopped:

```sh
quirebase restore /path/outside-data/backup.zip --force
quirebase doctor
quirebase reindex
```

`quirebase backup` refuses non-local object storage. S3 needs its own independent backup or
versioning policy. The bundled Garage service has one node and no bucket versioning; follow its
[snapshot instructions](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#object-storage).

## Upgrade an installation

1. Read the target release's instructions and stop all web and worker processes.
2. Create and verify a backup outside the installation's volumes.
3. Install matching Quirebase, Inquiro, and Excerpo versions. For source checkouts, rebuild frontend
   assets as well.
4. Apply the release's database instructions. `quirebase init-db` applies the installed migration
   chain and initializes workflow storage.
5. Run `quirebase doctor`, then restart web and workers with the new dependencies.

Quirebase is alpha software. A release may require recreating a database and reimporting content;
do not assume persisted workflow formats or earlier schemas are compatible. A rollback after a
database change requires the matching database backup, not just older packages. The detailed
[upgrade guide](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#upgrades) records
release-specific transitions, including DBOS workflow storage changes.

## Recover durable work

Restart a worker with the same executor ID to recover its in-flight workflows. If that executor is
permanently gone, inspect `quirebase recover-workflows OLD_EXECUTOR_ID` and apply recovery with
`--apply` after reviewing the listed workflows. Multiple workers must have distinct stable IDs.

## Understand retention

| Setting | Default |
| --- | --- |
| `QUIREBASE_ANNOTATION_UNDO_HOURS` | 24 hours |
| `QUIREBASE_WORKFLOW_HISTORY_RETENTION_DAYS` | 7 days |
| `QUIREBASE_TERMINAL_METADATA_RETENTION_DAYS` | 30 days |
| `QUIREBASE_AUDIT_RETENTION_DAYS` | 90 days |
| `QUIREBASE_IMPORT_BATCH_RETENTION_DAYS` | 7 days |

Import Batch retirement preserves committed Items and files while ending confirmation replay and
batch-scoped Library filtering. Terminal metadata retention applies to expired or revoked
credentials and invitations and terminated memberships. These settings do not establish automatic
content, account, or backup expiration.

Deleting retained records may make database space reusable without shrinking files. SQLite
compaction requires stopping all processes before `quirebase compact-sqlite`; PostgreSQL space
maintenance is separate. See [operations](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md).
