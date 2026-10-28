---
title: Manage your account and credentials
description: Change preferences, review Login Sessions, and manage API Tokens for integrations.
---

Open your user menu and choose **Account settings**. This page is available even when you have no
active Workspace membership; research content still requires access to a Workspace.

## Set your preferences

Choose the application language and whether navigation starts collapsed. The documentation site's
language selector controls the help pages separately from the application language.

The **Export preferences** section stores defaults for this browser. See
[citations and exports](/guides/citations-and-exports/) before relying on the same settings on
another browser or device.

## Change your password

Enter your current password and a new password of at least 12 characters, then choose
**Change password**. If you cannot sign in, contact your instance administrator rather than creating
another User to recover access to existing research content.

## Review Login Sessions

Under **Sessions**, review the creation and expiration times for signed-in devices. Revoke a session
you no longer use. Revoking the current session or all sessions signs you out; sign in again when
you need browser access.

A Login Session authenticates the browser. An API Token is a separate credential for HTTP API and
MCP clients; manage those in the **API Tokens** section.

## Create and replace an API Token

1. Under **API Tokens**, enter a recognizable name and choose an expiration period.
2. Choose **Create** and copy the plaintext token immediately. It is shown only once.
3. Expand **Client connection guide** for the installation's API and MCP endpoints.
4. Configure your client to send the token in the Bearer Authorization header.
5. Revoke unused tokens. To replace a credential, create a new token, update the intended client,
   verify it works, and revoke the old token.

If you lose the plaintext value, create a replacement rather than trying to retrieve it from token
history. A token has its User's current authority, without separate read-only or per-tool scopes.
Workspace membership changes and User deactivation affect access through the token as well.

See [HTTP API](/developers/http-api/) and [MCP](/developers/mcp/) for integration workflows.
