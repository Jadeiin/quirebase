---
title: Read, annotate, and export a PDF
description: Choose displayed sources and a write destination, verify saving, and download the intended marks.
---

Open an Item's **Files** section and choose **Read** for a ready PDF revision. If you still need to
upload or process it, follow [file management](/guides/files/).

An Annotation belongs to one page of one File Revision. Reopen that same revision when checking a
saved mark; another revision does not inherit its Annotations.

## Choose personal or shared notes before marking

Open **Annotations** in the reader. It contains two independent controls:

| Control | Changes what? |
| --- | --- |
| **Displayed annotation sources** checkboxes | Which of your private and readable Project sources are visible |
| **Save new annotations to** radio buttons | The private or editable Project destination for the next mark you create |

For a personal note, choose **Private annotations** under **Save new annotations to**. For a shared
note, first [add the Item to the Project](/guides/collaboration/#add-an-item-to-the-working-set), then
choose that Project under **Save new annotations to**. Only editable destinations are available.

**Example:** you display a Project's marks but leave the write destination on Private annotations.
Your new note is still private. Change the write destination before creating the mark you want
colleagues to read. An existing Annotation's audience is fixed at creation; it is not changed by
switching the displayed checkboxes or the destination for future marks.

## Create a mark and confirm it saved

1. Select the destination, then use the reader's tools to highlight text, place a note, or draw a mark.
2. Watch the save status while changes are being sent.
3. Wait for saving to complete before leaving the reader.
4. Reopen the same revision and enable the corresponding displayed source.

**Check the result:** the mark appears after reopening. A visible mark with a reported save failure
is not proof of a completed server save. Keep the reader open, inspect the error, and check current
authority and connectivity before refreshing. See [saving failures](/knowledge-base/troubleshooting/#annotation-saving-reports-a-failure).

Replies belong to their Annotation and inherit its visibility. Use an Item or Project **Discussion**
for a broader conversation that does not need a PDF page anchor.

## Download a PDF

1. Under **Displayed annotation sources**, enable only the private and Project sources intended for
   the export.
2. Open **Download**.
3. Choose **Download original** for the stored source, or **Download with annotations** for a temporary
   PDF containing the authorized displayed sources.
4. Download the finished result before the artifact expires. Generate another export if it expires.

The export leaves the original unchanged. This is an annotated PDF copy; flattened annotation
exports are unsupported. Password-protected PDFs and OCR are also unsupported.

## Understand removal before acting

Removing an Item from a Project permanently deletes that association's Project Annotations and
Replies across its PDF revisions. Private marks, the canonical Item, its files, and other Project
associations remain. Read the removal confirmation before proceeding.

Deleting a File Revision removes the marks anchored to that file. Deleting the canonical Item has
broader effects. If preservation is the task, export or keep the required context before deleting it.
