---
title: Manage account settings and credentials
description: Choose your language, review browser sessions, and create or revoke programmatic credentials.
---

Open the user menu in the application and choose **Account settings**. This page is available even
without an active Workspace membership; opening research content still requires Workspace access.

## Change language and browser preferences

Under **Preferences**, choose **Language** and whether navigation starts collapsed. The application
language and the documentation language selector are separate controls.

Use **Export preferences** to set citation and document defaults. These settings are local to this
browser; see [exports](/guides/citations-and-exports/) before expecting them on another device.

## Change your password

1. In **Password**, enter the current password.
2. Enter a new password of at least 12 characters.
3. Choose **Change password** and check the returned status.

If you cannot sign in, ask the instance administrator about account recovery. Creating another User
does not recover the first User's memberships, private Annotations, or authorship.

## Review and revoke browser sessions

Under **Sessions**, inspect creation/expiration times and the **Current session** marker. Use
**Revoke session** for a device you no longer use. Revoking the current session or choosing **Revoke
all sessions** signs you out; sign in again for browser access.

A browser Login Session and an API Token are separate credentials. To stop a programmatic client,
revoke its API Token in the next section rather than relying on browser sign-out.

## Create an API Token

1. Under **API Tokens**, enter a recognizable **Token name**, such as `Literature script`.
2. Choose an expiry period and select **Create**.
3. Copy the plaintext token from **Copy this token now** into the intended client's credential store.
4. Expand **Client connection guide** for this installation's HTTP API endpoint, OpenAPI link, and
   MCP configuration example.
5. Use the credential through the Bearer Authorization header and verify a Workspace-list request.

**Check the result:** the token appears in the account list with an expiration, and the client can
list the Workspaces your User may access. The plaintext value cannot be recovered later from history.

## Replace or revoke a token

To stop a client, choose **Revoke token** next to its credential. To rotate a working client, create
a replacement, update that client's stored credential, verify it, then revoke the previous token.
If the plaintext value was lost, create a replacement rather than trying to retrieve it.

Tokens carry the User's current authority, without separate read-only or per-tool scopes. Membership
changes, expiration, revocation, and User deactivation affect subsequent requests. Never put the
token into a query-string URL or send it to a scholarly Provider.

Continue with the complete [HTTP API](/developers/http-api/) or [MCP](/developers/mcp/) connection tutorial.
