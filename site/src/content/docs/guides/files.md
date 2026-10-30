---
title: Add and manage Item files
description: Attach the right kind of file, wait for PDF processing, and verify what is safe to remove.
---

Use this guide when the Item already exists. To create Items from a batch of PDFs, use
[PDF Import](/guides/import/#import-pdfs) first. Open the Item's **Files** section in its Workspace.

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
and add PDF**. Use a URL that directly downloads the PDF.

Uploading a corrected PDF creates another revision. Keep the old revision to continue using its
Annotations and page references.

## Upload an Attachment or Graphical Abstract

Use **Add attachment**, choose the supplementary file, and select **Upload attachment**. For a
representative image, select **Use as Graphical Abstract** before uploading. The URL attachment form
is available for downloadable remote files.

**Check the result:** the file appears in the list with the intended role. An Item has at most one
designated Graphical Abstract; that image takes priority over an automatically derived PDF thumbnail.

## Interpret processing states

| State | Meaning | What to do |
| --- | --- | --- |
| Pending | The revision is waiting for or undergoing inspection | Keep web and worker running; check the worker if the state does not progress |
| Ready | Extraction completed | Use **Read** and verify the document |
| Failed | Inspection failed and the source is retained | Inspect the error and use **Retry processing**, or add a corrected PDF |

Remove password protection before uploading a PDF. Scans can be read; text search needs a PDF
with a text layer. PDF and Attachment defaults allow up to 250 MiB per file, configurable by the
operator or reverse proxy. If an upload exceeds the limit, adjust the file or ask the operator to
change the limit.

## Download or remove a file

Use the file's **Download** action for stored content. For a PDF containing your marks, open that
revision and use [Download with annotations](/guides/pdf-annotations/#download-a-pdf).
An Item's document download action can also assemble selected revisions into a bundle.

Before choosing **Delete**, identify the exact revision or Attachment and keep any copy you need.
Deleting a File Revision removes its revision-bound Annotations and derived thumbnail. Deleting an
Attachment removes that supplementary file. Permanently deleting the Item removes its associated
files and context as well.
