# Quirebase

Quirebase is an AGPL-3.0-only, self-hosted collaborative research library. This directory contains the clean Python implementation; the legacy application is not required at runtime.

## Development

Requirements: Python 3.12+, `uv`, and Bun 1.3+ (or Node.js 22+ with npm) for building the bundled PDF.js assets.

```sh
uv sync --extra dev
uv run prek install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
bun install --frozen-lockfile
bun run build
uv run quirebase init-db
uv run quirebase create-admin
uv run quirebase serve
```

Run `uv run quirebase worker` in a second process. Configuration uses `QUIREBASE_` environment variables; the defaults use SQLite and `./quirebase-data`.

Before making a deployment available over a network, set `QUIREBASE_SOURCE_URL` to a public repository or archive containing the complete corresponding source for the exact deployed version. The application exposes this through its persistent **Source code** link.

For PostgreSQL install the `postgres` extra and set, for example:

```sh
QUIREBASE_DATABASE_URL=postgresql+psycopg://quirebase:password@localhost/quirebase uv run quirebase serve
```

## PDF architecture

- PDF.js is bundled locally and renders the document, text and annotation layers in the browser.
- PyMuPDF validates PDFs, extracts text, creates thumbnails, and writes database-backed highlights and notes into temporary export copies.
- Original PDFs are content-addressed and never modified.

Password-protected PDFs, OCR, flattened annotations and legacy-data migration are outside the first milestone.

## Search and bibliography interchange

- SQLite uses FTS5 and PostgreSQL uses a `tsvector`/GIN adapter behind the same search interface. Run `uv run quirebase reindex` after restoring a database or changing indexing rules.
- BibTeX and RIS imports are parsed into a persisted preview and only committed as one transaction after confirmation. Exports contain only items visible to the current user.

Quirebase is licensed under AGPL-3.0-only; see `LICENSE`. PyMuPDF is used under its AGPL option. The legacy application outside this directory retains its own license and is not relicensed by this rewrite.

## Completed scope

The rewrite includes local accounts and invitations, administrator/member and project owner/editor/viewer permissions, audited login attempts, per-session and all-session logout, durable login throttling, item metadata/custom fields, DOI/PMID/arXiv lookup with preview, tags, projects, discussions, PDF revisions, supplementary attachments, PDF.js reading and scoped annotations, PyMuPDF exports, dialect-native search, staged BibTeX/RIS import, audit events, resumable jobs, metrics, backup/restore, integrity checks, and a read-only legacy migration command.

Operational and migration instructions are in `docs/DEPLOYMENT.md` and `docs/LEGACY_MIGRATION.md`. Deferred integrations and their security gates are recorded in `docs/adr/0001-deferred-integrations.md`.

The real-paper validation suite uses separately downloaded, checksum-pinned PMC open-access PDFs. See `docs/TESTING.md`; run `uv run python scripts/download-oa-corpus.py`, `uv run pytest -q -m oa`, and `bun run test:oa:pdfjs`.
