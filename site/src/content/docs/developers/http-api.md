---
title: Connect an HTTP API client
description: Create a token, list Workspaces, select the right UUID, and make a first authenticated Library request.
---

Connect the client to your Quirebase application, for example `http://127.0.0.1:9060`. It serves JSON at
`/api/v1/`, interactive documentation at `/docs`, and its schema at `/openapi.json`.
The static [API Reference](/reference/api/) on this site is generated from the development checkout
and uses the schema's English descriptions. It may differ from your deployed version; use that
instance's `/openapi.json` or `/docs` as the source of truth for its API.

## Create a credential

1. Sign in to the application and open **Account settings → API Tokens**.
2. Create a named, expiring token and copy its plaintext value immediately.
3. Expand **Client connection guide** to confirm the application's endpoint.
4. Store the token in your client's credential mechanism and send it as `Authorization: Bearer …`.

An API Token executes requests as its User. Operators can also create a token from a source installation:

```sh
uv run quirebase create-api-token USERNAME --name "Research client" --days 30
```

Replace `USERNAME` with an existing User and save the one-time plaintext value in the client's credential store.

## Make the first request and choose a Workspace

For a curl client, set `QUIREBASE_URL` to the application root URL, make `QUIREBASE_API_TOKEN` available
through your local credential/environment setup, then run:

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $QUIREBASE_API_TOKEN" \
  "$QUIREBASE_URL/api/v1/workspaces?limit=10"
```

**Check the result:** a JSON pagination object contains `items`, `total`, `limit`, and `offset`. Choose
the target Workspace in `items` and use its `id` as the Workspace UUID.

Set `WORKSPACE_ID` to that UUID, then list ten Items:

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $QUIREBASE_API_TOKEN" \
  "$QUIREBASE_URL/api/v1/workspaces/$WORKSPACE_ID/items?limit=10"
```

The Workspace UUID in the path selects the Library to read. An empty Workspace returns an empty list.

## A runnable Python example

This standard-library example prompts for the token when run. Save it as
`list_library.py`, change the origin if necessary, and run it with Python:

```python
import json
from getpass import getpass
from urllib.request import Request, urlopen

origin = "http://127.0.0.1:9060"
token = getpass("API Token: ")


def get(path):
    request = Request(origin + path, headers={"Authorization": f"Bearer {token}"})
    with urlopen(request) as response:
        return json.load(response)


workspaces = get("/api/v1/workspaces?limit=100")
for workspace in workspaces["items"]:
    print(workspace["id"], workspace["name"])
workspace_id = input("Workspace UUID from this list: ").strip()
items = get(f"/api/v1/workspaces/{workspace_id}/items?limit=10")
print(json.dumps(items, ensure_ascii=False, indent=2))
```

The example lists the first page of Workspaces; follow each operation's pagination contract for a
complete client. If the Workspace list is empty, accept an invitation to the target Workspace, then run the example again.

## Handle errors and writes

| Result | What to check |
| --- | --- |
| 401 | Missing, invalid, expired, or revoked token |
| 403 | Current User/membership authority, lifecycle, or a cookie-authenticated request's Origin |
| 409 | A version or state conflict; reload the resource and review before retrying |
| Validation failure | Inspect `fields` and the running schema's required input constraints |

API errors contain `code` and `message`, with optional `fields` and `meta`. Handle errors by `code`
and use `fields` to locate input problems. Submit expected versions as required by each mutation
schema. Import follows preparation → preview review → confirmation that creates the Items.

For browser writes authenticated by a Login Session cookie, match the Origin to the application
configuration. See the [configuration guide](/administration/configuration/).
