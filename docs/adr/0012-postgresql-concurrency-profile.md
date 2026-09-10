# ADR 0012: PostgreSQL-first concurrency profile

Status: accepted.

## Decision

PostgreSQL is Quirebase's only deployment target with a supported multi-worker
concurrency guarantee. Row locks, DBOS projection workers, authorization
ordering and race-condition acceptance tests are specified and validated
against PostgreSQL.

SQLite remains a supported single-process, low-traffic development and demo
database. It retains migrations, backups and the SQLite FTS5 Search adapter,
but SQLite writer-lock emulation is not part of the business contract. SQLite
tests cover functional smoke paths only; PostgreSQL owns concurrency tests.

The implementation now contains nine SQLite-specific branches. They are limited
to URL/dialect selection, DBOS schema/isolation adaptation for local execution,
maintenance backup/restore, and the SQLite FTS adapter/upsert syntax. No business
authorization, lifecycle, Tag, Project or import path depends on a SQLite-only
writer gate.

Library Search is eventually consistent. Canonical mutations transactionally
enqueue a `SearchChanged(item_id, source_sequence)` DBOS workflow. Projection
failure retries independently after the canonical transaction has committed.

No API, stored-data or workflow-checkpoint compatibility layer is added for
this cutover.
