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
`postgresql-psycopgbinary` group. `QUIREBASE_DATABASE_URL` takes a
libpq URL
(`postgresql://...` or the `postgres://` alias) that the application opens with psycopg's native
async implementation and passes to `pg_dump` and `pg_restore` unchanged. SQLAlchemy driver
spellings such as `postgresql+psycopg://`, `postgresql+psycopg2://` and `postgresql+asyncpg://`
are rejected as configuration errors, so one URL serves the application, durable workflows and
maintenance tooling.
Set `QUIREBASE_DATABASE_URL`, `QUIREBASE_DATA_DIR`,
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
license separately.

Use a reverse proxy for TLS and request-size limits. Do not expose Uvicorn directly to the public internet. The bundled Compose deployment publishes its web port on loopback (`QUIREBASE_BIND_ADDRESS`, default `127.0.0.1`); set a host IP or `0.0.0.0` only when the reverse proxy cannot reach loopback. Preserve the application data directory independently from the installed wheel.

## Workers and recovery

One worker is the default deployment. Its executor ID (`quirebase-worker` unless
`QUIREBASE_WORKFLOW_EXECUTOR_ID` overrides it) is stable, so a restarted or recreated worker
recovers the workflows it had in flight when DBOS launches. The Compose worker keeps a fixed
container name, so `--scale worker=N` is refused instead of silently running replicas under one
identity; to run several workers, add one worker service per replica in a Compose override and
set a distinct `QUIREBASE_WORKFLOW_EXECUTOR_ID` for each. A workflow whose executor ID is gone
for good is listed and resumed manually with `quirebase recover-workflows <executor-id> --apply`.

## Object storage

`QUIREBASE_OBJECT_STORE=local` keeps immutable objects below
`QUIREBASE_DATA_DIR/objects`. For S3 or an S3-compatible service, set
`QUIREBASE_OBJECT_STORE=s3`, `QUIREBASE_S3_BUCKET`, and optionally
`QUIREBASE_S3_REGION`, `QUIREBASE_S3_ENDPOINT`, and `QUIREBASE_S3_PREFIX`. An HTTP
endpoint is accepted for private MinIO or Garage deployments; use TLS for traffic
crossing a trusted host boundary. `docker-compose.s3.yml` bundles a single-node Garage
service for the Compose deployment (`make docker-up-s3`); Garage bootstraps its access
key and bucket on first start, and the CI storage suite runs against the same image.
That bundled variant serves S3 region `us-east-1` as fixed by `docker/garage.toml`,
because Garage only reads its region from that file; configure a different region with an
external S3 service through the base compose file and `QUIREBASE_S3_REGION` instead. The
bundled Garage is one node with `replication_factor = 1` and no bucket versioning, and
`quirebase backup` refuses non-local object storage, so its volume holds the only copy of
every object. Treat `make docker-up-s3` as a single-host convenience deployment, keep an
independent snapshot or bucket mirror off the host, and stop the `garage` service while
snapshotting its volume:

    docker compose -f docker-compose.yml -f docker-compose.s3.yml --env-file .env.docker stop garage
    docker run --rm -v quirebase_garage-data:/source:ro -v "$PWD":/backup alpine \
        tar czf /backup/garage-data-$(date +%F).tgz -C /source .
    docker compose -f docker-compose.yml -f docker-compose.s3.yml --env-file .env.docker start garage

Restore by stopping the stack, extracting the archive into the `quirebase_garage-data`
volume, and starting it again. Production deployments should use an external S3 service
with versioning, replication or an independent backup policy.

Quirebase currently uses obstore's native S3 authentication. That implementation
reads the AWS environment configuration supported by obstore; in particular,
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optional `AWS_SESSION_TOKEN` can
be supplied to the web and worker processes. This is not a promise that every
source in botocore/boto3's credential-provider chain is consulted. obstore also
offers an optional `Boto3CredentialProvider` for applications that install boto3
and deliberately need botocore-compatible credential resolution, but Quirebase
does not install or select that provider by default.

Before switching an existing installation, copy every physical object below the
local object directory to the configured bucket/prefix while preserving its key.
The current release does not perform that external data migration automatically.
Web and every worker must use the same backend, bucket, and prefix.

## Backups

`quirebase backup backup.zip` creates a consistent SQLite snapshot or invokes `pg_dump` for PostgreSQL, adds immutable objects, and writes a checksum manifest. This backup/restore path currently requires the local object backend; protect an S3 bucket with its own versioning and backup policy, and snapshot or mirror the bundled Garage volume as described under Object storage. Verify a local backup with `quirebase verify-backup backup.zip`. Test restoration periodically on a separate installation. `quirebase restore backup.zip --force` replaces the configured database and overlays backed-up objects; stop all web and worker processes first.

`quirebase doctor` checks the schema, writable directories, PyMuPDF, the configured Recommendation
Engine and every stored object's SHA-256. `quirebase reindex` rebuilds the Library Search index. The
administrator page can retry failed jobs and rebuild all Item Tag Recommendations after an engine
or model change; `/metrics` exposes authenticated job and content counts. The worker installs an
hourly DBOS Schedule for export cleanup, Object Store integrity scanning and orphan reconciliation;
the schedule is persisted and does not depend on a process-local timer loop. File Revision work is
partitioned by revision with bounded worker/global concurrency, object cleanup uses its own
non-partitioned queue, and Recommendation inference is isolated from Library Search projection.

## Building assets from source

`src/quirebase/static` is a build output directory and is not tracked by git. From a source checkout, run `bun install` and `bun run build`; the script bundles `src/quirebase/assets` (with EmbedPDF, Alpine.js and zxcvbn from the pinned `package.json` dependencies), copies the handwritten `src/quirebase/assets/styles.css`, and copies EmbedPDF's PDFium WebAssembly binary to `static/vendor/pdfium.wasm`. Release wheels are built after this step and therefore ship the assets.

## Upgrades

Back up first, install the new wheel, run `quirebase init-db` to apply Alembic migrations, rebuild assets only for source checkouts (`bun install && bun run build`), restart web and worker processes, then run `quirebase doctor`.

**Alpha migration chain:** Quirebase is alpha software and a release may replace the migration chain instead of extending it. A database stamped by a revision that no longer exists cannot be upgraded in place: `quirebase init-db` and the Compose `migrate` service abort with `Can't locate revision`. Back up the installation so the old data is preserved, recreate the database (for Compose: `make docker-down DOWN_ARGS=--volumes`, then start the stack again), and reimport content through the application; cross-chain data migration is not provided.
