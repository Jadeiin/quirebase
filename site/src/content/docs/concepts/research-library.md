---
title: Items, files, and imports
description: Understand the records and content in a Quirebase research library.
---

| Concept | Meaning |
| --- | --- |
| Item | The bibliographic record stored in one Workspace |
| Work | The Item's Commonmeta bibliographic value, including title, type, identifiers, and Contributors |
| File Revision | One immutable primary PDF version belonging to an Item |
| Attachment | A supplementary Item file, optionally designated as its Graphical Abstract |
| Annotation | A mark or note anchored to one page of a File Revision, private or Project-scoped |
| Tag | A Workspace taxonomy label assigned explicitly to Items |
| Candidate Record | Uncommitted metadata prepared for review before Import |
| Import Batch | A temporary collection of sources, candidates, diagnostics, and confirmation results |

## A record and a file have different lifetimes

An Item can exist without a PDF and can have several File Revisions and Attachments. Its Work
metadata can be edited without changing its files. Annotations belong to a specific File Revision;
a newer PDF does not inherit the older PDF's geometry or marks.

The Item thumbnail uses its designated Graphical Abstract when present, otherwise an available
thumbnail from the newest eligible ready File Revision.

## Preparation and confirmation are separate

Discovery searches external Providers. Identifier Lookup retrieves metadata for supported
identifiers. Either can produce candidates for Import. Preparing candidates creates no Items.
Confirmation creates the selected Items and retains their identities in the committed Import Batch
for confirmation replay while that receipt remains.

Library Search searches stored Items and extracted local PDF text. It does not perform Discovery.

## Identifiers are not Item identities

Every Item has its own identity and Workspace lineage. An upstream DOI or other identifier describes
the Work. Several Items may carry the same upstream identifier, so duplicate suggestions require
review rather than automatic merging.

Continue with [Import](/guides/import/) or [Library organization](/guides/library-management/).
