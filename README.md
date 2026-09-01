# Quirebase

Quirebase is an AGPL-3.0-only, self-hosted collaborative research library.

## Development

Requirements: Python 3.12+, `uv`, and Bun 1.3+ (or Node.js 22+ with npm) for building the bundled PDF.js assets.

For a quick local test, run:

```sh
./scripts/dev.sh
```

This prepares dependencies and assets, initializes the development database, creates the
`admin` account with password `quirebase-dev` on the first run, and starts both the web server
and worker at <http://127.0.0.1:9060>. Override the defaults with
`QUIREBASE_DEV_HOST`, `QUIREBASE_DEV_PORT`, `QUIREBASE_DEV_USERNAME`, and
`QUIREBASE_DEV_PASSWORD`. Set `QUIREBASE_DEV_SKIP_SETUP=1` to skip dependency installation and
asset rebuilding on later runs.

For manual setup:

```sh
uv sync
uv run prek install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
bun install --frozen-lockfile
bun run build
uv run quirebase init-db
uv run quirebase create-admin
uv run quirebase serve
```

Run `uv run quirebase worker` in a second process. Configuration uses `QUIREBASE_` environment variables; the defaults use SQLite and `./quirebase-data`.

The default SQLite setup installs SQLAlchemy's `asyncio` and `aiosqlite` extras, so database
access never uses a synchronous Session bridge. For PostgreSQL install the `postgres` extra; it
selects SQLAlchemy's `postgresql-psycopgbinary` and `postgresql-asyncpg` groups (the configured
`postgresql+psycopg` URL uses psycopg's native async implementation) and set, for example:

```sh
QUIREBASE_DATABASE_URL=postgresql+psycopg://quirebase:password@localhost/quirebase uv run quirebase serve
```

## Programmatic access

Quirebase exposes authenticated library, project, document-metadata, annotation, tag, discussion,
Discovery and citation capabilities through a versioned JSON HTTP API at `/api/v1/` and MCP
Streamable HTTP at `/mcp/`. Both surfaces share response contracts and the same ordinary User
authorization rules; interactive OpenAPI documentation is available at `/docs`. They include reads and
ordinary User mutations; it deliberately excludes administrator operations, file bytes and the
currently unstructured PDF full text. A signed-in User can create and revoke their own time-limited
API Tokens under **Account settings → MCP and API Tokens**; that page also shows the deployment's
HTTP API and MCP endpoints plus an MCP client configuration example. Operators may alternatively use the CLI:

```sh
uv run quirebase create-api-token USERNAME --name "Research client" --days 30
```

The plaintext token is shown once. It has the User's current Quirebase permissions and no separate
tool scopes. Do not place it in a URL; send `Authorization: Bearer qb_api_...`. Inspect or revoke
tokens with `list-api-tokens USERNAME` and `revoke-api-token USERNAME TOKEN_ID`.

## PDF architecture

- PDF.js is bundled locally and renders the document, text and annotation layers in the browser.
- PyMuPDF validates PDFs, extracts text, creates thumbnails, and writes database-backed highlights and notes into temporary export copies.
- Original PDFs are content-addressed and never modified.

Password-protected PDFs, OCR and flattened annotations are outside the first milestone.

## Library Search, Discovery, and bibliography interchange

- SQLite uses FTS5 and PostgreSQL uses a `tsvector`/GIN adapter behind the same Library Search interface. Run `uv run quirebase reindex` after restoring a database or changing indexing rules.
- Discovery (online search) is separate from Import and provides fielded Boolean queries, source-specific sorting, year filters, pagination, and review-before-import across OpenAlex, Crossref, PubMed, arXiv, Open Library, PMC, NASA ADS, and IEEE Xplore (the latter two need API keys).
- BibTeX and RIS imports are parsed into a persisted preview and only committed as one transaction after confirmation. Exports contain only Items visible to the current user.
- Formatted citations use CSL styles via `citeproc-py`. Built-in styles require the optional `citation` extra (`uv sync --extra citation`); custom styles can be added from the Tools page without it.

Quirebase is licensed under AGPL-3.0-only; see `LICENSE`. PyMuPDF is used under its AGPL option.

## Completed scope

Quirebase includes local accounts and invitations, administrator/member and project owner/editor/viewer permissions, audited login attempts, per-session and all-session logout, durable login throttling, Item metadata/custom fields, DOI/PMID/arXiv/OpenAlex/ISBN lookup with preview, multi-source Discovery (online scholarly search), automatic DOI extraction from published PDFs, tags, dedicated project workspaces, duplicate-review and tag-management tools, discussions, PDF revisions, supplementary attachments, bulk citation/PDF export and owner-confirmed deletion, PDF.js reading with annotation detail panels, scoped annotations, PyMuPDF exports, dialect-native Library Search, staged BibTeX/RIS Import, audit events, resumable jobs, metrics, backup/restore, and integrity checks.

Operational instructions are in `docs/DEPLOYMENT.md`. Deferred integrations and their security gates are recorded in `docs/adr/0001-deferred-integrations.md`.

The real open-access PDF validation suite uses separately downloaded, checksum-pinned PMC open-access PDFs. See `docs/TESTING.md`; run `uv run python scripts/download-oa-corpus.py`, `uv run pytest -q -m oa`, and `bun run test:oa:pdfjs`.
