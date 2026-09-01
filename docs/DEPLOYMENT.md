# Deployment and operations

## Supported platforms

Python 3.12+ wheels are the common installation path on Windows, macOS and Linux. Install with `uv tool install` or in a virtual environment, then run `quirebase init-db`, `quirebase create-admin`, `quirebase serve`, and a separate `quirebase worker` process. PDF.js and UI assets are already included in release wheels.

Quirebase, `inquiro` and `rubrica` are versioned together and published to the same Python package
index. A release publishes the two standalone workspace packages before the matching Quirebase
artifact; Quirebase pins both dependencies to its own version so a standard wheel installation
cannot silently combine incompatible workspace releases. The release workflow verifies the full
wheel set in an isolated environment before publishing.

SQLite is intended for a single-host installation with one worker. The application uses SQLAlchemy's
`asyncio` and `aiosqlite` optional groups and derives `sqlite+aiosqlite` from the familiar
`sqlite:///...` setting. PostgreSQL is recommended for teams and supports concurrent workers
through `FOR UPDATE SKIP LOCKED`; the `postgres` extra installs SQLAlchemy's
`postgresql-psycopgbinary` and `postgresql-asyncpg` groups. A `postgresql+psycopg://...` setting
uses psycopg's native async implementation. Set `QUIREBASE_DATABASE_URL`, `QUIREBASE_DATA_DIR`,
`QUIREBASE_ALLOWED_HOSTS`, and secure cookies behind HTTPS. Native MCP clients send no `Origin`;
explicitly set `QUIREBASE_MCP_ALLOWED_ORIGINS` to a comma-separated list of trusted origins before
enabling browser-based MCP clients. Quirebase then handles CORS preflights for the MCP methods and
headers and exposes `MCP-Session-Id`; a `:*` suffix permits any numeric port for a named development
origin such as `http://localhost:*`.

The JSON HTTP API is served under `/api/v1/` and described by the application's OpenAPI document at `/openapi.json` and interactive `/docs` page. It accepts the same expiring API Tokens as MCP through `Authorization: Bearer`; Login Session cookies, CSRF tokens and query-string tokens are not API credentials. Cross-origin browser access to `/api/v1/` is not enabled by `QUIREBASE_MCP_ALLOWED_ORIGINS`.

For identifier lookup and Discovery (online scholarly search), set a monitored `INQUIRO_CONTACT_EMAIL`; NCBI and OpenAlex API keys are optional. See `METADATA_LOOKUP.md`. Restrictive egress firewalls should allow only the documented Provider hosts.

Tag Recommendations use offline YAKE by default. To use the optional semantic engine, install
`quirebase[keybert]`, set `QUIREBASE_RECOMMENDATION_ENGINE=keybert`, and point
`QUIREBASE_KEYBERT_MODEL_PATH` at an administrator-provisioned local Model2Vec directory. Runtime
model downloads and remote model identifiers are not supported. Record the model's source and
license separately, and set `QUIREBASE_KEYBERT_MODEL_SHA256` to pin its directory-content checksum.

Use a reverse proxy for TLS and request-size limits. Do not expose Uvicorn directly to the public internet. Preserve the application data directory independently from the installed wheel.

## Backups

`quirebase backup backup.zip` creates a consistent SQLite snapshot or invokes `pg_dump` for PostgreSQL, adds immutable objects, and writes a checksum manifest. Verify it with `quirebase verify-backup backup.zip`. Test restoration periodically on a separate installation. `quirebase restore backup.zip --force` replaces the configured database and overlays backed-up objects; stop all web and worker processes first.

`quirebase doctor` checks the schema, writable directories, PyMuPDF, the configured Recommendation
Engine and every stored object's SHA-256. `quirebase reindex` rebuilds the Library Search index. The
administrator page can retry failed jobs and rebuild all Item Tag Recommendations after an engine
or model change; `/metrics` exposes authenticated job and content counts.

## Building assets from source

`src/quirebase/static` is a build output directory and is not tracked by git. From a source checkout, run `bun install` and `bun run build`; the script bundles `src/quirebase/assets` (with `pdfjs-dist`, Alpine.js and zxcvbn from the pinned `package.json` dependencies) and copies the handwritten `src/quirebase/assets/styles.css` and the PDF.js vendor files into `static/`. Release wheels are built after this step and therefore ship the assets.

## Upgrades

Back up first, install the new wheel, run `quirebase init-db` to apply Alembic migrations, rebuild assets only for source checkouts (`bun install && bun run build`), restart web and worker processes, then run `quirebase doctor`.
