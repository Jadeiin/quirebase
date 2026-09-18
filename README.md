# Quirebase

Quirebase is an AGPL-3.0-only, self-hosted collaborative research library.

> [!IMPORTANT]
> Quirebase is currently alpha software. Development favors a clear current design over
> compatibility with earlier releases. APIs, database schemas, and persisted durable workflow
> inputs or checkpoints may change incompatibly; compatibility shims and replay support are added
> only when a release plan explicitly requires them.

## Development

Requirements: Python 3.12+, `uv` 0.12.14+, and Bun 1.4+ (or Node.js 22+ with npm) for building the Svelte application and bundled PDFium asset.

For a quick local test, run:

```sh
./scripts/dev.sh
```

This prepares dependencies, initializes the development database, creates the
`admin` account with password `quirebase-dev` on the first run, and starts Vite with HMR at
<http://127.0.0.1:5173>, FastAPI at <http://127.0.0.1:9060>, and the durable worker. Vite proxies
API requests to FastAPI, and the development external origin is set to the Vite origin so
cookie-authenticated mutations keep the production Origin policy. Override the defaults with
`QUIREBASE_DEV_HOST`, `QUIREBASE_DEV_PORT`, `QUIREBASE_DEV_FRONTEND_PORT`,
`QUIREBASE_DEV_USERNAME`, and `QUIREBASE_DEV_PASSWORD`. Set `QUIREBASE_DEV_SKIP_SETUP=1` to skip
dependency installation on later runs.

For manual setup:

```sh
uv sync
uv run prek install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
bun install --cwd frontend --frozen-lockfile
bun run --cwd frontend build
uv run quirebase init-db
uv run quirebase create-admin
uv run quirebase serve
```

Run `uv run quirebase worker` in a second process. Configuration uses `QUIREBASE_` environment variables; the defaults use SQLite and `./quirebase-data`.

The default SQLite setup installs SQLAlchemy's `asyncio` and `aiosqlite` extras, so database
access never uses a synchronous Session bridge. For PostgreSQL install the `postgres` extra; it selects SQLAlchemy's
`postgresql-psycopgbinary` group. `QUIREBASE_DATABASE_URL` takes a libpq
URL that the application opens with psycopg's native async implementation and passes to `pg_dump`
and `pg_restore` unchanged, for example:

```sh
QUIREBASE_DATABASE_URL=postgresql://quirebase:password@localhost/quirebase uv run quirebase serve
```

## Programmatic access

Quirebase exposes authenticated library, project, document-metadata, annotation, tag, discussion,
Discovery and citation capabilities through a versioned JSON HTTP API at `/api/v1/` and MCP
Streamable HTTP at `/mcp/`. The curated MCP tool surface is generated from the OpenAPI contract and
executes those same API operations, so both surfaces share response contracts and ordinary User
authorization rules; interactive OpenAPI documentation is available at `/docs`. They include reads
and ordinary User mutations; MCP deliberately excludes administrator operations, file bytes and the
currently unstructured PDF full text. A signed-in User can create and revoke their own time-limited
API Tokens under **Account settings → MCP and API Tokens**; that page also shows the deployment's
HTTP API and MCP endpoints plus an MCP client configuration example. Operators may alternatively use the CLI:

```sh
uv run quirebase create-api-token USERNAME --name "Research client" --days 30
```

The plaintext token is shown once. It has the User's current Quirebase permissions and no separate
tool scopes. Do not place it in a URL; send `Authorization: Bearer qb_api_...`. Inspect or revoke
tokens with `list-api-tokens USERNAME` and `revoke-api-token USERNAME TOKEN_ID`.

API errors return a stable JSON object with `code` and `message`, plus optional `fields` for request
validation and `meta` for structured conflict details.

## PDF architecture

- EmbedPDF's Svelte viewer components and bundled PDFium engine render the document, text and annotation layers in the browser.
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

Quirebase includes local accounts and invitations, administrator/member and project owner/editor/viewer permissions, audited login attempts, per-session and all-session logout, durable login throttling, Item metadata/custom fields, DOI/PMID/arXiv/OpenAlex/ISBN lookup with preview, multi-source Discovery (online scholarly search), automatic DOI extraction from published PDFs, tags, dedicated project workspaces, duplicate-review and tag-management tools, discussions, PDF revisions, supplementary attachments, bulk citation/PDF export and owner-confirmed deletion, EmbedPDF reading with annotation detail panels, scoped annotations, PyMuPDF exports, dialect-native Library Search, staged BibTeX/RIS Import, audit events, a global background-task tray for resumable jobs, metrics, backup/restore, and integrity checks.

Operational instructions are in `docs/DEPLOYMENT.md`. Deferred integrations and their security gates are recorded in `docs/adr/0001-deferred-integrations.md`.

The real open-access PDF validation suite uses separately downloaded, checksum-pinned PMC
open-access PDFs. See `docs/TESTING.md`; run
`uv run python scripts/download-oa-corpus.py` and `uv run pytest -q -m oa`.
