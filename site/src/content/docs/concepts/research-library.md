---
title: Understand Items, files, and annotations
description: Follow one reference through import, PDF revisions, private notes, and Project collaboration.
---

Suppose you keep a journal article in a Workspace, upload its published PDF, and later add a corrected
PDF. You still have **one Item**, with **two File Revisions**. A private note on the first PDF belongs
to that first revision; it does not appear on the corrected PDF automatically.

If you add this Item to two Projects, both Projects refer to the same Workspace record. Each can
hold its own Project Annotations and Discussions. Updating the Item metadata updates that shared
record, while private marks and each Project's reading context have their own visibility.

## Match the term to the thing you are editing

| Term | What it represents | Example |
| --- | --- | --- |
| Item | A bibliographic record in one Workspace | The journal article in Library |
| Work | The Item's Commonmeta bibliographic value | Title, type, identifiers, Contributors, and dates |
| File Revision | One immutable primary PDF | Published PDF, then corrected PDF |
| Attachment | A supplementary Item file | Supporting data or a representative image |
| Annotation | A mark anchored to one page of one revision | A highlight on page 3 of the published PDF |
| Annotation Reply | A response inheriting an Annotation's visibility | A colleague's reply to a Project highlight |
| Tag | A Workspace classification explicitly assigned to Items | `Methods` or `To read` |
| Project | A working set inside the Workspace | A reading group using some of its Items |
| Candidate Record | Metadata not yet committed to Library | A record shown in an Import preview |
| Import Batch | Sources, candidates, diagnostics, and a retained confirmation result | The batch prepared from a bibliography |

A Contributor is a credited person or organization on the Work, not necessarily a Quirebase User.
Matching author names across Items do not establish one shared researcher identity.

## Search, prepare, and confirm have different results

| Action | Where it looks or writes | Does it create Items? |
| --- | --- | --- |
| Library Search | Saved Workspace metadata and extracted PDF text | No |
| Discovery | External scholarly Providers | No |
| Identifier Lookup / import preparation | Provider metadata or uploaded source data | No; it creates candidates for review |
| Import confirmation | The selected Workspace | Yes, according to the prepared batch and basic-PDF selection |
| Manual creation | The selected Workspace | Yes, when you choose **Create Item** |

A committed Import Batch retains its created Item IDs while its receipt exists. Deleting that
receipt keeps the Items and files, but ends confirmation replay and its Library batch filter.

## Identity and lifetime

An Item has its own UUID and Workspace lineage. A DOI identifies the bibliographic Work; several
Items may carry the same DOI, so duplicate suggestions require review. A Citation Key is an editable
name for citation output, not the Item's identity or its permission owner.

An Item can exist without a PDF. Metadata edits do not replace its files. Deleting one revision
removes its revision-bound marks and thumbnail; deleting a Project association removes that
association's Project marks and Replies; deleting the canonical Item has broader effects.

Continue with [Workspace access](/concepts/workspaces-and-projects/) or follow the
[first-reference walkthrough](/getting-started/quickstart/).
