# Quirebase repository guidance

## Alpha compatibility policy

Quirebase is alpha software. Optimize changes for the current design. Add compatibility layers for
an earlier release's APIs, stored data, or persisted durable workflow inputs and checkpoints only
when the task or an explicit release plan requires them. Preserve correctness within the current
version, including concurrent requests, retries, and durable recovery.

## Database migrations

Migrations live in `migrations/`, configured by `[tool.alembic]` in `pyproject.toml` and
`alembic.ini`. Create revisions with `uv run alembic revision --autogenerate -m "..."` from the
repository root and commit the generated file; never hand-write revision identifiers or edit the
chain, and only change the upgrade/downgrade bodies. Alembic's template assigns random
12-character identifiers that fit the `alembic_version.version_num` column it creates. Add every
schema change as a new revision on top of the existing chain; do not replace or edit a committed
revision unless there is exceptional necessity, such as repairing a chain that cannot be applied
to a supported database.

Every migration must apply to a fresh SQLite and a fresh PostgreSQL database: CI runs
`quirebase init-db` and `quirebase doctor` for both. Keep dialect-specific schema, such as the FTS5
and `tsvector` search tables, behind `op.get_bind().dialect.name` branches, and keep metadata
autogenerate-friendly. Domain state columns use `native_enum=False` with explicit CHECK
constraints, so PostgreSQL enum support packages such as `alembic-postgresql-enum` are
unnecessary.

## Agent skills

### Issue tracker

Issues are tracked in GitHub Issues (via `forge` CLI).
See `docs/agents/issue-tracker.md`.

### Triage labels

Use the canonical `needs-triage`, `needs-info`, `ready-for-agent`,
`ready-for-human`, and `wontfix` states.
See `docs/agents/triage-labels.md`.

### Domain and module architecture

Before changing business behaviour, capability ownership, cross-package dependencies or test
seams, use the root domain glossary, repository decisions and module policy.
See `docs/agents/domain.md`.
