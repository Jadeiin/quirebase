---
title: Manage account settings and credentials
description: Choose your language, review browser sessions, and create or revoke programmatic credentials.
---

Open the application's user menu and choose **Account settings**.

## Change language and browser preferences

Under **Preferences**, choose **Language** and whether navigation starts collapsed. The application
language and the documentation language selector are separate controls.

Use **Export preferences** to set citation and document defaults. These settings are local to this
browser; see [exports](/guides/citations-and-exports/) before expecting them on another device.

## Change your password

1. In **Password**, enter the current password.
2. Enter a new password of at least 12 characters.
3. Choose **Change password** and check the returned status.

If you cannot sign in, ask the instance administrator to help recover your account.

## Review and revoke browser sessions

Under **Sessions**, inspect creation/expiration times and the **Current session** marker. Use
**Revoke session** for a device you no longer use. Revoking the current session or choosing **Revoke
all sessions** signs you out; sign in again for browser access.

To stop a programmatic client's access, revoke its API Token in the next section.

## Create an API Token

1. Under **API Tokens**, enter a recognizable **Token name**, such as `Literature script`.
2. Choose an expiry period and select **Create**.
3. Copy the plaintext token from **Copy this token now** into the intended client's credential store.
4. Expand **Client connection guide** for this installation's HTTP API endpoint, OpenAPI link, and
   MCP configuration example.
5. Use the credential through the Bearer Authorization header and verify a Workspace-list request.

**Check the result:** the token appears in the account list with an expiration, and the client can
list the Workspaces your User may access.

## Replace or revoke a token

To stop a client, choose **Revoke token** next to its credential. To rotate a working client, create
a replacement, update that client's stored credential, verify it, then revoke the previous token.
Create a replacement if the token is lost.

Clients access Workspaces as the token's User. Store the token in the client's credential store
and send it through the Bearer header.

Continue with the complete [HTTP API](/developers/http-api/) or [MCP](/developers/mcp/) connection tutorial.
