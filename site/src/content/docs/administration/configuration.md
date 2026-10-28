---
title: Configure an installation
description: Choose database, storage, access, Provider, and worker settings.
---

Quirebase reads `QUIREBASE_` environment variables and a `.env` file in the working directory.
The Compose deployment uses `.env.docker`. Configure web and worker consistently; changes require
restarting the affected processes.

## Core settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `QUIREBASE_DATABASE_URL` | `sqlite:///./quirebase.db` | SQLite file or PostgreSQL libpq connection URL |
| `QUIREBASE_DATA_DIR` | `./quirebase-data` | Persistent application data directory |
| `QUIREBASE_OBJECT_STORE` | `local` | `local` objects below the data directory, or `s3` |
| `QUIREBASE_ALLOWED_HOSTS` | `localhost,127.0.0.1,testserver` | Accepted HTTP hostnames, comma separated |
| `QUIREBASE_EXTERNAL_ORIGIN` | Unset | Public origin used to validate browser mutations |
| `QUIREBASE_SECURE_COOKIES` | `false` | Enable for HTTPS deployments |
| `QUIREBASE_REGISTRATION_POLICY` | `invitation_only` | `open`, `closed`, or `invitation_only` |
| `QUIREBASE_WORKSPACE_CREATION_POLICY` | `admins_only` | `admins_only` or `members_allowed` |
| `QUIREBASE_WORKFLOW_EXECUTOR_ID` | `quirebase-worker` | Stable, unique worker identity |

These are the application defaults. Compose overrides some settings, including the database URL,
data directory, and accepted hosts. See the repository's
[Compose example](https://github.com/Jadeiin/quirebase/blob/main/.env.docker.example).

## Metadata Providers and citations

Set `INQUIRO_CONTACT_EMAIL` to a monitored address for scholarly Provider identification.
Optional credentials include `INQUIRO_NCBI_API_KEY`, `INQUIRO_OPENALEX_API_KEY`,
`INQUIRO_NASA_ADS_TOKEN`, and `INQUIRO_IEEE_API_KEY`. Provider capabilities and available choices
are exposed in the application; do not assume all Providers support every identifier or query.

Install the optional `citation` extra to include built-in CSL styles. Custom styles can be added
through **Tools** without the extra.

Tag Recommendations use offline YAKE by default. The optional `keybert` extra requires
`QUIREBASE_RECOMMENDATION_ENGINE=keybert` and `QUIREBASE_KEYBERT_MODEL_PATH` pointing to
administrator-provisioned local Model2Vec files. Runtime model downloads are unsupported.

## Object storage

For S3-compatible storage, set `QUIREBASE_OBJECT_STORE=s3`, `QUIREBASE_S3_BUCKET`, and the
applicable `QUIREBASE_S3_REGION`, `QUIREBASE_S3_ENDPOINT`, and `QUIREBASE_S3_PREFIX` settings.
Supply native AWS credentials to web and worker processes. Copy existing objects with their keys
preserved before switching backends; changing configuration does not migrate data.

Keep application streaming for container-only endpoints. Direct signed downloads require a
browser-reachable endpoint and separately configured bucket CORS. See the detailed
[storage contract](https://github.com/Jadeiin/quirebase/blob/main/docs/DEPLOYMENT.md#object-storage).

## Browser MCP access

Native MCP clients normally send no Origin. Browser-based clients require an explicit
`QUIREBASE_MCP_ALLOWED_ORIGINS` allowlist. This configures MCP CORS only; it does not enable
cross-origin browser access to `/api/v1/` or configure your S3 bucket.

Use [API Tokens](/developers/http-api/) for programmatic clients and
[maintenance](/administration/maintenance/) for retention and recovery settings.
