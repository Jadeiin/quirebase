---
title: Search external sources
description: Build a Discovery query, review candidates, and send the intended results to Import.
---

Use **Discovery** when you know a topic, title, or author and want to search scholarly Providers.
For content already saved in Quirebase, use [Library Search](/guides/library-management/).
Save selected results to Library through Import preview and confirmation.

## Before searching

Choose the destination Workspace. Searching and importing use your current Workspace authority.
Available Providers, fields, and sorting depend on the installation's configuration and each
Provider's capabilities. If no sources are available, ask the operator to check Provider settings.

## Run one simple query

1. Open **Discovery** and choose a **Provider**.
2. In the first search condition, choose **Title** or **Any field** and enter a phrase such as
   `graph neural networks`.
3. Optionally set **From year**, **To year**, and a supported sort order.
4. Choose **Search Discovery**.

**Check the result:** candidate records appear, with titles, authors, and publication details. Use
**Show abstract** to inspect a candidate before deciding to import it.

## Narrow or combine conditions

Use **Add condition** for another field and choose **AND**, **OR**, or **NOT** where supported. For
example, combine a title condition with an author condition using **AND**. Every condition needs a
search term; enter the year range from earlier to later.

OpenAlex supports **OR** between adjacent conditions on the same
field. After switching Providers, review the available fields and sort order before searching again.
Start with fewer conditions when a query fails or finds nothing.

## Review and import a result

For one candidate, choose **Review and import**. To prepare a group, select candidates and choose
**Review selected**. A batch can contain up to 50 candidates, and the selected candidates must use
the same identifier type to be reviewed together.

The application looks up their metadata and opens an Import preview. Review that prepared preview
and its diagnostics, then choose **Import … records**. The preview contains the freshly retrieved
metadata that will be saved.

**Check the result:** the preview shows **Import completed** and **View imported Items** opens the
created records in the destination Workspace. Continue with [Import preview behavior](/guides/import/#review-the-preview-and-commit-once).

## If a step fails

| Symptom | Next action |
| --- | --- |
| No candidates | Try fewer conditions, another field, a wider year range, or another Provider |
| Unsupported query | Check the selected Provider's available fields, operators, and sort options |
| Candidate selected but no Item in Library | Complete the Import preview and confirmation |
| Metadata preview fails | Check its diagnostics; retry temporary failures or import a supported identifier separately |
