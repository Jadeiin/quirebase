---
title: Frequently asked questions
description: Understand imports, private notes, Project visibility, file revisions, and export limits.
---

## I can see an Import preview. Why is the Item missing from Library?

Preparation creates candidates, not Items. Check the preview, then choose **Import … records**.
After completion, use **View imported Items** and verify the Workspace. Manual creation is different:
**Create Item** saves directly. See [Import](/guides/import/).

## Which preview records can I choose?

Identified records are committed together. In **PDFs without metadata**, explicitly select the basic
PDF candidates you want to keep; unselected ones are skipped. If the identified batch is wrong,
discard it and correct the inputs. [The preview guide](/guides/import/#review-the-preview-and-commit-once)
explains the confirmation count.

## Does a managed Project hide its Items from everyone else?

It limits discovery of the Project collaboration context. Canonical Items still follow Workspace
access. Project participation does not grant extra Item authority. Use a different Workspace when a
separate membership boundary is required; copying across Workspaces creates independent records.

## Why can a viewer create a private note?

Private Annotations belong to their author. In an active Workspace, all five roles may maintain their
own private notes. Shared Project Annotation creation has different grants. See [roles](/administration/workspaces-and-members/).

## Can an instance administrator read my private notes?

Instance administration has no implicit Workspace-content access, and private Annotations remain
author-restricted. Reason-bound read-only inspection and ownership reassignment are explicit,
audited governance operations, not general browsing authority. See [access concepts](/concepts/workspaces-and-projects/).

## My colleague cannot see my mark. What should I check?

Check that both of you opened the same PDF revision. Your mark must have been created with the
Project selected under **Save new annotations to**, and the colleague must enable that Project as a
displayed source and have the required authority. Showing a Project source does not make a new
private mark shared. See [PDF annotations](/guides/pdf-annotations/).

## Do annotations move to a new PDF revision?

No automatic migration is performed. Each mark is anchored to one page of one revision. Keep the
old revision if you need its marks. An export creates a copy without changing the stored source.

## Can I use a scanned or password-protected PDF?

OCR and password-protected PDFs are unsupported. An image-only scan may render without producing
searchable text. Flattened annotation exports are also unsupported.

## Does deleting import history remove the imported Items?

Deleting or expiring a committed batch preserves its Items and files. It removes the retained
confirmation result and corresponding Library filter. Import history is not a backup of source files.

## What is removed when I leave a Workspace?

Leaving terminates your membership and its explicit Project selections, while preserving content
and authorship. Rejoining needs a new invitation and does not restore prior selections. Owners need
to transfer ownership before leaving.

## Why are my saved views or export preferences different on another device?

They are browser-local preferences, scoped to the account and, where applicable, the Workspace.
They are not server-synchronized research content. Recheck the current browser's settings.

## Is a bibliography export enough for backup?

It exchanges reference metadata. It does not replace a database-and-object backup, including
membership, Discussions, and stored files. Follow [backup and restore](/administration/maintenance/).

## How do integrations authenticate?

Use an expiring API Token with the [HTTP API](/developers/http-api/) or [MCP](/developers/mcp/).
Tokens use the User's current authority. The installation's `/docs` and `/openapi.json` describe its
own running release; the static reference retains schema descriptions in English.
