---
title: Add and manage Item files
description: Attach the right kind of file, wait for PDF processing, and verify what is safe to remove.
---

Use this guide when the Item already exists. To create Items from a batch of PDFs, use
[PDF Import](/guides/import/#import-pdfs) first. Open the Item's **Files** section in its Workspace.
File management and permanent Item deletion are separate permissions.

## Choose a file role

| You are adding | Use | Result |
| --- | --- | --- |
| A primary paper or corrected main PDF | **Add PDF revision** | A separate immutable File Revision that can be processed and opened in the reader |
| Supplementary data or another supporting file | **Add attachment** | An Attachment associated with the Item |
| A representative image | **Add attachment**, with **Use as Graphical Abstract** | The Item's designated Graphical Abstract |

An Item can have several PDF revisions. Each revision has its own pages and Annotations.

## Upload a primary PDF

1. Under **Add PDF revision**, choose the file and select **Upload PDF**.
2. Wait for its processing state to become ready. The worker inspects the PDF and extracts text and
   page geometry.
3. Choose **Read** beside that revision.
4. Confirm the title and filename in the reader refer to the file you intended.

For a direct PDF download URL, use **Add a PDF from URL**, enter the address, and choose **Download
and add PDF**. The address should return a PDF file, not an article landing page requiring browser
navigation or sign-in. This download operation is separate from Identifier Lookup.

Uploading a corrected PDF creates another revision; it does not replace the older revision or move
its Annotations. Keep the old revision if you need its marks and page references.

## Upload an Attachment or Graphical Abstract

Use **Add attachment**, choose the supplementary file, and select **Upload attachment**. For a
representative image, select **Use as Graphical Abstract** before uploading. The URL attachment form
is available for downloadable remote files.

**Check the result:** the file appears in the list with the intended role. An Item has at most one
designated Graphical Abstract; that image takes priority over an automatically derived PDF thumbnail.
An Attachment does not become the reader's primary PDF revision.

## Interpret processing states

| State | Meaning | What to do |
| --- | --- | --- |
| Pending | The revision is waiting for or undergoing inspection | Keep web and worker running; check the worker if the state does not progress |
| Ready | Extraction completed | Use **Read** and verify the document |
| Failed | Inspection failed and the source is retained | Inspect the error and use **Retry processing**, or add a corrected PDF |

Password-protected PDFs and OCR are unsupported. An image-only scan may render without producing
searchable text. PDF and Attachment defaults allow up to 250 MiB per file; an operator or reverse
proxy can impose different limits. Check the actual upload error rather than retrying the same
oversized request repeatedly.

## Download or remove a file

Use the file's **Download** action for stored content. For a PDF containing your marks, open that
revision and use [Download with annotations](/guides/pdf-annotations/#download-a-pdf).
An Item's document download action can also assemble selected revisions into a bundle.

Before choosing **Delete**, identify the exact revision or Attachment and keep any copy you need.
Deleting a File Revision removes its revision-bound Annotations and derived thumbnail. Deleting an
Attachment removes that supplementary file. Permanently deleting the Item removes its associated
files and context as well. These are different operations with different scopes.
