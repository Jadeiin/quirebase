---
title: Add your first reference
description: Save one reference, attach its PDF, add a private note, and verify the result.
---

This walkthrough assumes you can sign in to an existing Quirebase installation. Ask its administrator
for the application URL and an account or account Invitation. To run Quirebase yourself, follow
[deployment](/administration/deployment/) first.

By the end, you will have one **Item** in a **Workspace**, a primary PDF **File Revision**, and a
private **Annotation**. Have a PDF ready to attach.

## 1. Choose the destination Workspace

1. Sign in and open **My workspaces**, or use the Workspace menu in the application sidebar.
2. Open the Workspace where this reference should live. Check its name before importing.

After creating an account, open your own Workspace from **My workspaces**. To join a team, accept
the team's Workspace Invitation.

## 2. Look up a DOI and confirm it

1. Open **Import → Identifiers**.
2. Paste `10.1073/pnas.92.6.2288` into the identifier field. Leave **Data source** on **Auto detect**.
3. Choose **Preview metadata** to see the candidate records.
4. Check the title, Contributors, publication details, and any import issues. The identified records
   shown in this preview will be imported together when you confirm.
5. Choose **Import … records** at the bottom of the preview.
6. When the preview shows **Import completed**, choose **View imported Items**.

**Check the result:** the Item appears in Library in the Workspace you selected. Open it to inspect
its Metadata.

If metadata lookup is unavailable, use **Import → Manual creation**, enter a title and the reference
information you know, and choose **Create Item**. Manual creation saves an Item directly.
See [all import methods](/guides/import/) for bibliography and PDF imports.

## 3. Attach and open a PDF

1. Open the Item and select **Files**.
2. Under **Add PDF revision**, choose the PDF and select **Upload PDF**.
3. Wait until processing is ready, then choose **Read** for that file.

**Check the result:** the PDF reader opens the expected document. If processing stays pending, the
operator should check the separate worker process. If it fails, use **Retry processing** when offered
or add a corrected PDF. See [file management](/guides/files/).

## 4. Make a private note

1. In the reader, open **Annotations**.
2. Under **Save new annotations to**, choose **Private annotations**.
3. Use an annotation tool to mark a passage or add a note.
4. Wait for the save status to confirm saving before leaving the reader.
5. Reopen the same PDF revision and ensure **Private annotations** is included in the displayed sources.

**Check the result:** the mark is visible after reopening the same revision. See the
[PDF annotation guide](/guides/pdf-annotations/) for more reading tools.

## 5. Choose the next task

- [Find and organize Library](/guides/library-management/) with Tags, filters, and saved views.
- [Create a Project and share Annotations](/guides/collaboration/) with colleagues.
- [Export a citation or bibliography](/guides/citations-and-exports/) for writing.
