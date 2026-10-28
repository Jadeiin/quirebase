---
title: Troubleshoot common problems
description: Diagnose import, processing, authorization, save, and configuration failures.
---

## Import or PDF processing stays pending

Check whether the separate `quirebase worker` process is running with the same database and object
storage settings as web. Preparing PDFs and other durable jobs needs that worker. Operators can
inspect job state in the administrator interface and run `quirebase doctor`.

If a worker was replaced with a different executor ID, follow
[durable recovery](/administration/maintenance/#recover-durable-work).

## Metadata cannot be identified

Confirm the input is a supported identifier rather than an arbitrary article URL. Prefix ISBN-10
values with `ISBN:`. Review each preview diagnostic; a failure for one source does not invalidate
successful candidates. Retry temporary metadata failures when offered, select a basic PDF candidate
explicitly, or enter metadata manually.

Operators should check Provider credentials, outbound connectivity, and `INQUIRO_CONTACT_EMAIL`.
See [Import](/guides/import/) and [configuration](/administration/configuration/).

## An action is missing or access is denied

Check the selected Workspace, active User and membership status, role, and resource lifecycle.
A frozen Workspace blocks mutations. A Project may be archived or have managed participation.
Being an instance administrator or a Project participant does not independently grant Item access.

Ask a Workspace governor to review the relevant authority. Do not work around the failure by changing
resource IDs or repeatedly replaying a rejected mutation.

## Annotation saving reports a failure

Keep the reader open while inspecting the error and its save state. Check connectivity, the selected
annotation destination, Project lifecycle, and whether the Item remains associated with that
Project. Concurrent changes can require reviewing the latest resource state before retrying.
Do not assume a visible local mark has reached the server after a reported save failure.

## A download fails or an export has expired

Create a new Annotation export and retry while authorized. If direct S3 downloads are enabled,
operators should verify that the signed endpoint is browser-reachable and bucket CORS permits the
application origin, range requests, and the required response headers. A container hostname such as
`garage` is not normally browser-reachable; use application streaming for that topology.

## Sign-in works but browser changes fail behind a proxy

Set `QUIREBASE_EXTERNAL_ORIGIN` to the exact public scheme, hostname, and port. Confirm the request
origin matches, `QUIREBASE_ALLOWED_HOSTS` contains the public hostname, and secure cookies are used
over HTTPS. MCP CORS settings do not configure the HTTP API's browser Origin policy.

## Get help with evidence

Report the Quirebase version, the failing task, a redacted error `code` and `message`, and the
response's `X-Request-ID` when available. Operators can correlate it with logs and health diagnostics.
Do not include passwords, API Tokens, private research files, or unredacted connection URLs in a
public issue. Use the repository's [issue tracker](https://github.com/Jadeiin/quirebase/issues).
