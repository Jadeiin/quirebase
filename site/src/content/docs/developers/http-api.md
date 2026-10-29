---
title: Connect an HTTP API client
description: Create a token, list Workspaces, select the right UUID, and make a first authenticated Library request.
---

Use your application's origin, not the documentation host. The running application serves JSON at
`/api/v1/`, interactive documentation at `/docs`, and its schema at `/openapi.json`.
The static [API Reference](/reference/api/) on this site is generated from the development checkout
and keeps the schema's English descriptions. Use the running installation's schema for a different release.

## Create a credential

1. Sign in to the application and open **Account settings → API Tokens**.
2. Create a named, expiring token and copy its plaintext value immediately.
3. Expand **Client connection guide** to confirm the application's endpoint.
4. Store the token in your client's credential mechanism and send it as `Authorization: Bearer …`.

The token carries the User's current authority without extra per-tool scopes. It cannot bypass a
missing Workspace membership. Operators can also create a token from a source installation:

```sh
uv run quirebase create-api-token USERNAME --name "Research client" --days 30
```

Replace `USERNAME` with an existing User. The plaintext value is shown once. Do not put it in a URL.

## Make the first request and choose a Workspace

For a curl client, set `QUIREBASE_URL` to the application origin, make `QUIREBASE_API_TOKEN` available
through your local credential/environment setup, then run:

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $QUIREBASE_API_TOKEN" \
  "$QUIREBASE_URL/api/v1/workspaces?limit=10"
```

**Check the result:** a JSON pagination object contains `items`, `total`, `limit`, and `offset`. Choose
an accessible Workspace's `items[].id`. This is a Workspace UUID, not a username, Item ID, or Project ID.

Set `WORKSPACE_ID` to that UUID, then list ten Items:

```sh
curl --fail-with-body \
  -H "Authorization: Bearer $QUIREBASE_API_TOKEN" \
  "$QUIREBASE_URL/api/v1/workspaces/$WORKSPACE_ID/items?limit=10"
```

An empty Item list can be a valid result for an empty Workspace. A research request still needs
explicit Workspace path context even when the User belongs to only one Workspace.

## A runnable Python example

This standard-library example prompts for the token instead of placing it in the source. Save it as
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
complete client. Do not submit a blank Workspace ID when no accessible Workspaces were returned.

## Handle errors and writes

| Result | What to check |
| --- | --- |
| 401 | Missing, invalid, expired, or revoked token; an explicit invalid Authorization header does not fall back to a browser cookie |
| 403 | Current User/membership authority, lifecycle, or a cookie-authenticated request's Origin |
| 409 | A version or state conflict; reload the resource and review before retrying |
| Validation failure | Inspect `fields` and the running schema's required input constraints |

API errors contain `code` and `message`, with optional `fields` and `meta`. Use machine-readable codes
rather than matching English messages. Mutation schemas may require expected versions; preserve
those values. Import requires preparation, preview review, and explicit confirmation rather than
assuming a successful lookup has created an Item.

Bearer requests and browser Login Session cookies are separate authentication modes. Unsafe
cookie-authenticated requests require the correct Origin. MCP's CORS allowlist does not enable
cross-origin browser requests to `/api/v1/`.
