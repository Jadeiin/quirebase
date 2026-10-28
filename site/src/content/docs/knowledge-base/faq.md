---
title: Frequently asked questions
description: Answers about imports, visibility, PDF support, and programmatic access.
---

## Why is my imported reference missing from Library?

Preparing an Import Batch does not create Items. Review the preview and confirm your selection.
Check that you are viewing the destination Workspace and that Library filters do not exclude it.
See [Import](/guides/import/).

## Does joining a Project grant access to its Items?

Project participation grants no additional Workspace authority or canonical Item access. Workspace
membership and resource-action policy govern the Items. A managed Project limits discovery of its
collaboration context, not access to its canonical Items within the Workspace.

## Can an instance administrator read all research data?

An instance administrator has no implicit access to Workspace research data. Account and instance
governance are separate from Workspace content authority. See [access concepts](/concepts/workspaces-and-projects/).

## Does a new PDF revision carry over annotations?

Annotations are anchored to one page of one File Revision. Another revision does not inherit them.
Keep the original revision when you need its marks. [Annotation exports](/guides/pdf-annotations/)
create temporary copies and leave the stored source unchanged.

## Are scanned or password-protected PDFs supported?

Quirebase does not provide OCR or password-protected PDF support. An image-only PDF can lack
searchable extracted text. Flattened annotation exports are also unsupported.

## Does deleting an import record delete its Items?

Deleting a committed Import Batch keeps imported Items and files. It removes the retained
confirmation result and the batch-scoped Library filter. Unconfirmed staging is temporary and
follows the configured retention policy.

## Can I edit this help center in the application?

Documentation is maintained as Markdown and MDX in Git. Use a page's edit link to propose a change.
Research content, Annotations, and Discussions live in the application; this documentation site has
its own independent static build.

## Which API should an integration use?

Use the [HTTP API](/developers/http-api/) for direct requests or [MCP](/developers/mcp/) for a client
that supports its curated research tools. Both use expiring API Tokens and current User authority.
The installation's own `/docs` and `/openapi.json` describe its running release.
