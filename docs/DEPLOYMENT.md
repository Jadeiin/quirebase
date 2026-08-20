# Deployment and operations

## Supported platforms

Python 3.12+ wheels are the common installation path on Windows, macOS and Linux. Install with `uv tool install` or in a virtual environment, then run `quirebase init-db`, `quirebase create-admin`, `quirebase serve`, and a separate `quirebase worker` process. PDF.js and UI assets are already included in release wheels.

SQLite is intended for a single-host installation with one worker. PostgreSQL is recommended for teams and supports concurrent workers through `FOR UPDATE SKIP LOCKED`. Set `QUIREBASE_DATABASE_URL`, `QUIREBASE_DATA_DIR`, `QUIREBASE_ALLOWED_HOSTS`, and secure cookies behind HTTPS.

For identifier lookup and Discovery (online scholarly search), set a monitored `QUIREBASE_METADATA_CONTACT_EMAIL`; NCBI and OpenAlex API keys are optional. See `METADATA_LOOKUP.md`. Restrictive egress firewalls should allow only the documented Provider hosts.

Use a reverse proxy for TLS and request-size limits. Do not expose Uvicorn directly to the public internet. Preserve the application data directory independently from the installed wheel.

## Backups

`quirebase backup backup.zip` creates a consistent SQLite snapshot or invokes `pg_dump` for PostgreSQL, adds immutable objects, and writes a checksum manifest. Verify it with `quirebase verify-backup backup.zip`. Test restoration periodically on a separate installation. `quirebase restore backup.zip --force` replaces the configured database and overlays backed-up objects; stop all web and worker processes first.

`quirebase doctor` checks the schema, writable directories, PyMuPDF and every stored object's SHA-256. `quirebase reindex` rebuilds the Library Search index. The administrator page can retry failed jobs; `/metrics` exposes authenticated job and content counts.

## Building assets from source

`src/quirebase/static` is a build output directory and is not tracked by git. From a source checkout, run `bun install` and `bun run build`; the script bundles `src/quirebase/assets` (with `pdfjs-dist`, Alpine.js and zxcvbn from the pinned `package.json` dependencies) and copies the handwritten `src/quirebase/assets/styles.css` and the PDF.js vendor files into `static/`. Release wheels are built after this step and therefore ship the assets.

## Upgrades

Back up first, install the new wheel, run `quirebase init-db` to apply Alembic migrations, rebuild assets only for source checkouts (`bun install && bun run build`), restart web and worker processes, then run `quirebase doctor`.
