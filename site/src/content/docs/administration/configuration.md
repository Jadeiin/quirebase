---
title: Configure an installation
description: Understand configuration precedence, set a working baseline, and choose database, storage, and Provider options.
---

Configure web and worker for the same installation. First distinguish startup settings from values
that an administrator has saved in the application.

## Know which value takes effect

| Source | Where it is set | How it takes effect |
| --- | --- | --- |
| Deployment environment | Process environment or a working-directory `.env` | Process environment overrides `.env`; restart affected processes after changes |
| Compose environment | `.env.docker` and `docker-compose.yml` | Apply changes with `make docker-up`; Compose also supplies database/data-directory defaults |
| Runtime settings | The administrator Settings page | For supported keys, saved database values override deployment defaults |

Runtime overrides include registration and Workspace-creation policies, Provider contact/credentials,
session duration, upload byte limits, and export lifetime. Read their effective values on the
administrator Settings page. Database connection,
object-store backend, origin, and worker identity remain deployment settings.

## Set a local baseline

For a source checkout, create `.env` in the directory where you run `uv run quirebase …`:

```dotenv
QUIREBASE_DATABASE_URL=sqlite:///./quirebase.db
QUIREBASE_DATA_DIR=./quirebase-data
QUIREBASE_ALLOWED_HOSTS=localhost,127.0.0.1
QUIREBASE_EXTERNAL_ORIGIN=http://127.0.0.1:9060
QUIREBASE_SECURE_COOKIES=false
INQUIRO_CONTACT_EMAIL=operator@example.org
```

Use your monitored email address. This example is for local HTTP access. For public HTTPS, use the
actual hostname/origin and secure cookies described in [deployment](/administration/deployment/).
Relative filesystem paths resolve from the process working directory, so web and worker must agree.

## Select database and admission policy

| Setting | Application default | Meaning |
| --- | --- | --- |
| `QUIREBASE_DATABASE_URL` | `sqlite:///./quirebase.db` | SQLite file or PostgreSQL libpq connection URL |
| `QUIREBASE_DATA_DIR` | `./quirebase-data` | Persistent application data |
| `QUIREBASE_REGISTRATION_POLICY` | `invitation_only` | `open`, `closed`, or `invitation_only` account admission |
| `QUIREBASE_WORKSPACE_CREATION_POLICY` | `admins_only` | `admins_only` or `members_allowed` for additional Workspaces |
| `QUIREBASE_WORKFLOW_EXECUTOR_ID` | `quirebase-worker` | Stable worker identity; use a different value for each worker |

These are application defaults; see `.env.docker` for the Compose configuration. Account creation
provides a Workspace, and the additional-Workspace policy controls creating more. Use Settings to verify
runtime policy overrides. For PostgreSQL source installs, include the `postgres` extra before starting.

## Configure Providers and citation support

Set `INQUIRO_CONTACT_EMAIL` for Provider identification. Available optional credentials are
`INQUIRO_NCBI_API_KEY`, `INQUIRO_OPENALEX_API_KEY`, `INQUIRO_NASA_ADS_TOKEN`, and `INQUIRO_IEEE_API_KEY`.
Some sources require credentials; the application exposes the available lookup/search choices.
Check the administrator's saved runtime values as well as environment defaults.

Built-in Citation Styles require the `citation` extra (`uv sync --frozen --extra citation` for a
source checkout). Preserve other needed extras when synchronizing, such as `--extra postgres`.
The Docker image includes PostgreSQL and citation extras. Authorized Users can add custom styles.

Tag Recommendations use offline YAKE by default. For the optional local KeyBERT engine, install the
`keybert` extra, set `QUIREBASE_RECOMMENDATION_ENGINE=keybert`, and point
`QUIREBASE_KEYBERT_MODEL_PATH` to an administrator-provisioned local Model2Vec directory.

## Configure file storage and limits

Local objects use `QUIREBASE_DATA_DIR/objects`. For S3-compatible storage, set:

```dotenv
QUIREBASE_OBJECT_STORE=s3
QUIREBASE_S3_BUCKET=your-bucket
QUIREBASE_S3_REGION=your-region
```

Also set the applicable endpoint/prefix and native AWS credentials for both web and workers. For an
existing installation, migrate files with their physical object keys intact, then update the
configuration. See [maintenance](/administration/maintenance/) for S3 backup.

PDF and Attachment limits default to `262144000` bytes (250 MiB) each. The settings are
`QUIREBASE_MAX_PDF_BYTES` and `QUIREBASE_MAX_ATTACHMENT_BYTES`, with possible administrator runtime
overrides. Enter byte values and align the proxy's request-size limit.

Keep streaming downloads for container-only S3 hostnames. Direct signed downloads need a
browser-reachable endpoint and separately configured bucket CORS. See the detailed
[object-storage contract](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#object-storage)
for endpoint, signature, and migration requirements.

## Browser MCP access

Add browser MCP clients' Origins to the `QUIREBASE_MCP_ALLOWED_ORIGINS` allowlist.

After configuration, run the [health and recovery checks](/administration/maintenance/) with the
same installation settings.
