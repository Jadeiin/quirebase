---
title: Find and organize Items
description: Search your Library, maintain metadata, apply Tags, and export references.
---

## Search your Workspace

Open **Library** in the intended Workspace. Library Search covers stored Items and extracted local
PDF text. It does not query external scholarly Providers. Use **Discovery** for that task.

Combine search with the filters and sorting shown in Library. Open an Item to inspect its
**Overview**, **Metadata**, **Files**, **Organize**, **Annotations**, and **Discussion** sections.

## Maintain reference details

Use **Metadata** to check the title, ordered Contributors, identifiers, Reference Type, publication
details, and Citation Key. An Item stores a bibliographic Work; a PDF is a File Revision associated
with that Item. Uploading a newer PDF does not create a new version of the bibliographic record.

Items may share an upstream identifier. Duplicate suggestions help you review those records;
they do not automatically merge them. Check metadata and files before deciding what to keep.

## Organize with Tags and Projects

Use **Organize** to maintain Tag assignments and Project associations. Tags are shared Workspace
taxonomy labels. Provider keywords and recommended Tags become assignments only after you select
them. Use **Tools** to maintain Tags, including rename and merge operations, when permitted.

A Project contains a working set of Workspace Items. Adding an Item to a Project preserves the
canonical Item and lets the Project hold its own Annotations and Discussions.
See [collaboration](/guides/collaboration/) before removing a Project association.

The Library selection controls offer bulk actions according to your permissions. Check the selected
set before applying an action, especially when changing filters or pages.

## Review duplicates

Open **Tools → Duplicate review**, choose **Shared identifier**, **Same title**, or **Same PDF**, and
run **Check for duplicates**. Matching criteria matter: title matching uses exact values, including
case and formatting, and PDF checks use ready files. A result group suggests records to inspect;
it does not merge them.

Compare each Item's metadata, files, Project associations, and Annotations before retaining or
deleting a record. Permanent Item deletion removes the associated content and requires a separate
Workspace permission.

## Copy to another Workspace

Use an Item's **Copy to Workspace** action, select an available destination, and choose **Create
copy**. Open the result in the destination and verify its metadata and files.

A cross-Workspace copy creates a new canonical Item, with independent governance. It does not create
a live sharing relation or keep future edits synchronized. The source must allow export and the
destination must allow Item creation; the command rechecks both before committing.

## Export references and citations

Use the Item or Library actions to export BibTeX, RIS, CSL-JSON, or Commonmeta, or copy a formatted
bibliography. Exports include only Items visible to you. A Citation Key is format-independent and
can be edited on the Item.

Formatted citations require an available CSL Citation Style. Operators can install the optional
`citation` extra for built-in styles; custom styles can be added through **Tools** without it.
For PDF output, use [Download with annotations](/guides/pdf-annotations/#download-a-pdf).
For formats, browser defaults, and document bundles, see [citations and exports](/guides/citations-and-exports/).
