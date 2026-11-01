---
title: Frequently asked questions
description: Find answers about imports, team access, reading notes, browser preferences, and backups.
---

## I can see an Import preview. Why is the Item missing from Library?

Check the preview, then choose **Import … records**. After completion, use **View imported Items**
and verify the destination Workspace. See [Import](/guides/import/) for the complete procedure.

## Which preview records can I choose?

Identified records are committed together. In **PDFs without metadata**, explicitly select the basic
PDF candidates you want to keep. [The preview guide](/guides/import/#review-the-preview-and-commit-once)
explains how to adjust a batch and check the confirmation count.

## How should I arrange reference access for different teams?

Create a Workspace for each team with a different membership and assign appropriate roles.
Within a Workspace, use Projects for reading groups and shared references. See
[Workspaces and Projects](/concepts/workspaces-and-projects/).

## Which roles suit reading and review?

Viewers can read, export, and keep private notes. Reviewers can also contribute shared Project
Annotations, Replies, and Discussions. See [member management](/administration/workspaces-and-members/)
for more roles.

## Who can see my Annotations?

Private Annotations are visible to their author. Project Annotations are shared with participants
who have reading permission. Choose Private annotations or the target Project under
**Save new annotations to** when creating a mark.

## My colleague cannot see my mark. What should I check?

Open the same PDF revision, check the Project where the mark was saved, and ask your colleague to
enable that Project under **Displayed annotation sources**. See
[PDF annotations](/guides/pdf-annotations/) for the complete procedure.

## How can I view Annotations on an older PDF?

Find the original PDF revision in the Item's **Files**, choose **Read**, and enable the relevant
Annotation sources. Each revision keeps its own marks, available as long as you retain the revision.

## What does a PDF need for reading and text search?

Upload a PDF with password protection removed. Scans can be read; full-text search needs a PDF
with a text layer. See [file management](/guides/files/) for preparation and processing states.

## Does deleting import history remove the imported Items?

Deleting or expiring a committed batch preserves its Items and files. It removes the retained
confirmation result and corresponding Library filter.

## What is removed when I leave a Workspace?

Leaving terminates your membership and its explicit Project selections, while preserving content
and authorship. Returning members accept a new invitation and arrange their Project participation
again. Owners transfer ownership before leaving.

## Why are my saved views or export preferences different on another device?

These preferences are stored in the current browser for the account and Workspace. Set up your
preferred views and export defaults when using a new device.

## How can I back up the whole installation?

Ask the operator to follow [backup and restore](/administration/maintenance/) for the database and
object files, preserving membership, references, Discussions, and stored files.

## How do integrations authenticate?

Use an expiring API Token with the [HTTP API](/developers/http-api/) or [MCP](/developers/mcp/).
Tokens use the User's current authority. The installation's `/docs` and `/openapi.json` describe its
own running release; the static reference retains schema descriptions in English.
