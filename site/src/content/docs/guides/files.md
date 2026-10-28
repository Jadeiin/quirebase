---
title: Add and manage Item files
description: Upload a primary PDF revision, add supplementary Attachments, and recover processing failures.
---

Open the Item's **Files** section in the intended Workspace. Maintaining its files requires file
management authority; metadata, file, and deletion permissions are evaluated separately.

## Add a primary PDF

Under **Add PDF revision**, choose a PDF and select **Upload PDF**. Quirebase stores a new immutable
File Revision and processes it with the durable worker. Wait for the ready state, then choose
**Read** to open that revision in the PDF reader.

To download a primary PDF directly from its source, use **Add a PDF from URL** and provide a direct
PDF URL. This file-download operation differs from metadata lookup: arbitrary article landing-page
URLs are not supported by Identifier Import.

Every primary PDF upload creates a distinct revision. Uploading a corrected file does not replace
the older revision or move its Annotations. Keep the older revision when you need its original marks
and page references.

## Add supplementary files

Under **Add attachment**, choose a file and select **Upload attachment**. Use
**Add attachment from URL** for a downloadable supplementary file. An Attachment is separate from a
primary PDF revision and does not become the PDF reader's main document.

Select **Use as Graphical Abstract** for an appropriate representative image. An Item has at most
one designated Graphical Abstract. It takes priority over derived first-page PDF thumbnails when
the application chooses the Item image.

## Recover a failed revision

A failed File Revision retains its source. Choose **Retry processing** when available; operators
should confirm that a worker is running with the same database and storage settings as web.
If the file itself is invalid, add a corrected PDF and verify it before deciding whether to delete
the failed revision. Password-protected PDFs and OCR are unsupported.

An image-only scan may render without producing searchable text. For stalled jobs and download
problems, follow [troubleshooting](/knowledge-base/troubleshooting/).

## Download or delete files

Use the file's **Download** action for its stored content. To export marks, open its revision in the
reader and choose **Download with annotations**. Item **Download** actions can also assemble a bundle
of selected PDF revisions according to your [export preferences](/guides/citations-and-exports/).

Deleting a File Revision removes its revision-bound Annotations and derived thumbnail. Deleting an
Attachment removes that supplementary file. These actions are separate from permanently deleting
the Item, which removes its associated files and context as well. Review what you need to preserve
before confirming deletion.
