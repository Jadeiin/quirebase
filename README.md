# Quirebase

Quirebase is an AGPL-3.0-only, self-hosted collaborative research library.

Discover papers, organize your Library, annotate PDFs together, and take your references into writing.

<picture>
<img alt="Quirebase in action: discover papers, preview a bibliography import, organize references, highlight a PDF, reply to a shared annotation, and export citations." src="https://github.com/user-attachments/assets/7bd512c7-fb0d-48c5-add6-966ca87a7a04" />
</picture>

> [!IMPORTANT]
> Quirebase is alpha software. APIs, database schemas and durable workflow formats may change
> without backward compatibility.

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
uv run --frozen prek install --hook-type pre-commit --hook-type pre-push --hook-type commit-msg
bun install --cwd frontend --frozen-lockfile
bun run --cwd frontend build
uv run quirebase init-db
uv run quirebase create-admin
uv run quirebase serve
```

Run `uv run quirebase worker` in a second process. Configuration uses `QUIREBASE_` environment variables; the defaults use SQLite and `./quirebase-data`.

For PostgreSQL, install the `postgres` extra and set a libpq database URL, for example:

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

API errors return a JSON object with `code` and `message`, plus optional `fields` for request
validation and `meta` for structured conflict details.

Research data access is governed by Workspace resource-action decisions. Workspace roles are
`owner`, `admin`, `editor`, `reviewer` and `viewer`; Project participation is role-less and never
grants access to canonical Workspace Items. Permanent Item deletion requires the Workspace
`item.delete` action. An instance administrator has no implicit access to research data.

## PDF architecture

- EmbedPDF's Svelte viewer components and bundled PDFium engine render the document, text and annotation layers in the browser.
- PyMuPDF validates PDFs, extracts text, creates thumbnails, and writes database-backed highlights and notes into temporary export copies.
- Logical PDF uploads use independently owned UUID object keys. Annotation exports leave the original PDF unchanged.

Password-protected PDFs, OCR and flattened annotation exports are unsupported.

## Library Search, Discovery, and bibliography interchange

- SQLite uses FTS5 and PostgreSQL uses a `tsvector`/GIN adapter behind the same Library Search interface. Run `uv run quirebase reindex` after restoring a database or changing indexing rules.
- Discovery (online search) is separate from Import and provides fielded Boolean queries, source-specific sorting, year filters, pagination, and review-before-import across OpenAlex, Crossref, PubMed, arXiv, Open Library, PMC, NASA ADS, and IEEE Xplore (the latter two need API keys).
- BibTeX, RIS, CSL-JSON and Commonmeta imports are parsed into a persisted preview and committed after confirmation. Exports contain only Items visible to the current User.
- Formatted citations use CSL styles via `citeproc-py`. Built-in styles require the optional `citation` extra (`uv sync --extra citation`); custom styles can be added from the Tools page without it.

## Documentation

- [Deployment and operations](docs/DEPLOYMENT.md)
- [Import and Discovery](docs/METADATA_LOOKUP.md)
- [Testing and development checks](docs/TESTING.md)
- [Domain glossary](GLOSSARY.md) and [module ownership](docs/architecture/modules.md)
- [Third-party licenses](THIRD_PARTY.md); PyMuPDF is used under its AGPL option.
