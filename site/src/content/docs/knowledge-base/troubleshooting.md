---
title: Troubleshoot a failed task
description: Start from the symptom, check the current state, and follow the recovery steps.
---

Start with the symptom, inspect the current resource or job state, and follow the steps below.
Use the installation's actual Workspace, version, and configuration.

| You observe | Start by checking |
| --- | --- |
| Import preview but no saved Item | Confirmation status and destination Workspace |
| Confirmation outcome unknown | **Check import status** to see the result |
| PDF processing stays pending | Running worker and shared database/storage configuration |
| An action is missing | Membership, role, freeze/archive state, and target relationship |
| A colleague cannot see a mark | PDF revision, original write destination, and displayed sources |
| Browser changes fail behind a proxy | Public Origin, host allowlist, HTTPS cookie settings |
| Environment changes appear ineffective | Administrator runtime overrides for supported settings |

## Import or PDF processing stays pending

1. Return to **Import history** or the Item's **Files** section and inspect the retained state.
2. The operator checks whether the separate worker is running. For Compose, use `make docker-ps`
   and inspect the worker's entries in `make docker-logs` (Ctrl+C stops following logs).
3. Verify web and worker use the same database and object backend, including bucket/prefix if relevant.
4. Run Doctor with that installation's configuration and inspect failed diagnostics.

After a worker replacement, keep its stable executor ID. If an old executor is permanently gone,
use [durable recovery](/administration/maintenance/#recover-durable-work).

## An import result is uncertain or missing

If the application cannot confirm whether Import completed, use **Check import status**. If it is
committed, open **View imported Items**. If Library appears empty, check the Workspace and active
filters, including the batch filter.

For missing metadata, inspect each diagnostic. Use supported identifiers, prefix ISBN-10 with
`ISBN:`, retry temporary source failures when offered, or explicitly keep a basic PDF candidate and
edit its metadata later. See [Import](/guides/import/) for supported input formats.

## An action is missing or access is denied

Ask the Workspace owner or admin to check your membership status and role. Then check whether the
Workspace is frozen, the Project is archived, and you have joined the target Project. Follow
[member management](/administration/workspaces-and-members/) to restore access or adjust roles.

## Annotation saving reports a failure

Keep the reader open and inspect the save status. Check network connectivity, the selected write
destination, whether the Project is still active, and whether its Item association still exists.
A concurrent change may require reviewing the current resource before retrying.

Once saving works again, reopen the same File Revision and enable the corresponding source to
verify the Annotations.

## A download or export fails

An expired Annotation Export needs a fresh export while you still have authority. If direct S3
signed downloads are enabled, check that the endpoint is reachable from the browser and bucket CORS
allows the application origin, range requests, and required response headers. A hostname like
`garage` may be reachable only inside the container network; use application streaming there.

## Sign-in works but browser changes fail behind a proxy

Set `QUIREBASE_EXTERNAL_ORIGIN` to the exact public scheme/host/port, include the public host in
`QUIREBASE_ALLOWED_HOSTS`, and use secure cookies with HTTPS. Restart/recreate the affected services
and retry from the configured application origin.

## A configuration edit does not take effect

Verify the process working directory and environment first. Then inspect the administrator Settings
page: supported runtime values override environment defaults. Database, object-store, origin, and
worker deployment settings require consistent process configuration and restart. See
[configuration precedence](/administration/configuration/#know-which-value-takes-effect).

## Report a problem with useful evidence

Include the Quirebase version, task and selected Workspace context, redacted error `code`/`message`,
and `X-Request-ID` when available. Operators can correlate the request ID with logs. Redact credentials
and private information from logs, screenshots, and connection URLs before submitting public feedback.
The [issue tracker](https://github.com/Jadeiin/quirebase/issues) is the repository's public reporting channel.
