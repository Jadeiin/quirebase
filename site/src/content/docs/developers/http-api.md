---
title: Use the HTTP API
description: Authenticate with an API Token, select a Workspace, and follow the generated API contract.
---

Your installation serves the JSON HTTP API at `/api/v1/`, its OpenAPI schema at `/openapi.json`, and
interactive documentation at `/docs`. The static [API Reference](/reference/api/) on this site is
generated from the current source; use your installation's schema when running a different release.

## Create a credential

Sign in and open **Account settings → API Tokens**. Create a time-limited API Token and copy
it from the one-time response. That page also shows your installation's HTTP API and MCP endpoints.
Expand **Client connection guide** for connection examples. Operators can alternatively run:

```sh
quirebase create-api-token USERNAME --name "Research client" --days 30
```

Send the token in `Authorization: Bearer qb_api_...`. It carries its User's current authority,
without separate tool scopes. Revocation, expiration, User deactivation, and membership changes
affect subsequent access. Do not put the token in a URL or pass it to a scholarly Provider.

## Select a Workspace

Set `QUIREBASE_URL` to your application's origin and `QUIREBASE_API_TOKEN` to the credential in your
client's environment. List accessible Workspaces:

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $QUIREBASE_API_TOKEN" \
  "$QUIREBASE_URL/api/v1/workspaces"
```

Choose an accessible Workspace ID before using Workspace-scoped routes. For example, list its Items:

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $QUIREBASE_API_TOKEN" \
  "$QUIREBASE_URL/api/v1/workspaces/$WORKSPACE_ID/items"
```

Follow each operation's generated pagination, validation, and response schema. Preserve concurrency
versions required by mutation inputs; after a conflict, reload and review the latest state before
retrying. Import uses preparation, preview review, and explicit confirmation.

## Handle errors and authentication

API errors contain `code` and `message`, with optional `fields` for validation details and `meta` for
structured conflicts. Branch on stable machine-readable values rather than matching message text.

The browser application uses Login Session cookies and Origin checks for unsafe requests. An
explicit Authorization header selects Bearer authentication. MCP's Origin allowlist does not enable
cross-origin browser requests to the HTTP API.

Route fields, status codes, and examples belong to the [generated reference](/reference/api/).
Contribute API descriptions in the FastAPI routes and schemas so the frontend types, MCP projection,
and documentation use the same contract.
