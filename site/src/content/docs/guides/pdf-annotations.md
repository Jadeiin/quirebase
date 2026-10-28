---
title: Read and annotate PDFs
description: Choose an annotation audience, check saving, and download an annotated PDF.
---

## Open a File Revision

Open an Item's **Files** section and select a ready primary PDF. A File Revision is an immutable PDF
version: pending while it is inspected, ready after successful extraction, or failed with its source
retained for retry. Supplementary files are Attachments, separate from primary PDF revisions.
See [file management](/guides/files/) for uploads and processing recovery.

Annotations bind to a page of one File Revision. Uploading another revision does not move existing
marks onto the new file.

## Choose where new annotations go

In the reader, open **Annotations**:

1. Under **Displayed annotation sources**, select your private annotations and the Project sources
   you want to read.
2. Under **Save new annotations to**, select **Private annotations** or an editable Project.
3. Use the reader's annotation tools to add marks and notes.
4. Check the save status before leaving the page. Resolve a reported save failure before reloading.

Displayed sources and the destination for new annotations are separate controls. Showing a Project's
annotations does not make newly created private notes shared. An Annotation's private or Project
audience is fixed when created; change the destination before creating a mark for another audience.

Replies inherit the Annotation's visibility. Item and Project Discussions are separate conversations
and have no PDF geometry.

:::caution[Removing an Item from a Project]
Removing the Project–Item association permanently deletes that association's Project Annotations
and Replies. The canonical Item, its files, private Annotations, and other Project associations
remain. Check with collaborators before removing it.
:::

## Download a PDF

- **Download → Download original** returns the original File Revision.
- **Download → Download with annotations** creates a temporary PDF using the displayed annotation
  sources that you are authorized to read.

Exports leave the stored original unchanged. Download the result before the export artifact expires;
create another export if needed. Flattened annotation exports, password-protected PDFs, and OCR are
currently unsupported.

For processing, saving, or download failures, see [troubleshooting](/knowledge-base/troubleshooting/).
