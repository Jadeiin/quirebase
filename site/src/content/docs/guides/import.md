---
title: Import references and PDFs
description: Review identifiers, bibliography data, or PDFs before adding Items to a Workspace.
---

Select the destination Workspace and open **Import**. Import requires permission to create Items.

| Source | Input |
| --- | --- |
| Identifiers | Up to 50 supported identifiers or identifier URLs, one per line |
| Bibliography | A UTF-8 file or pasted BibTeX, RIS, CSL-JSON, or Commonmeta data, up to 5 MiB |
| PDFs | PDF files from which Quirebase prepares metadata candidates |
| Manual creation | Details entered directly in the metadata editor |

## Look up identifiers

Keep **Auto detect** selected or choose an available Provider explicitly. For example:

```text
10.1073/pnas.92.6.2288
https://pubmed.ncbi.nlm.nih.gov/11607519/
arXiv:2304.08030
ISBN:0674016394
```

Prefix ISBN-10 values with `ISBN:` to distinguish them from PubMed IDs.
General website and article landing-page URLs are unsupported. Use a supported identifier or
manual creation. PMCID lookup is currently unsupported, although PMC is available for Discovery.

## Review before confirming

Preparation creates an Import Batch containing Candidate Records and diagnostics.
Review titles, Contributors, publication details, and the selected candidates before confirmation.
Provider metadata can be incomplete. Confirming creates the selected Items in the destination
Workspace; document processing and Tag Recommendations may continue afterward.

Successful candidates remain available when other inputs fail. Refreshing a preview preserves the
prepared batch. For temporary metadata failures, use **Retry metadata** when offered.

For PDFs without identified metadata, explicitly select the basic PDF candidates you want to keep.
You can fill in their metadata after import. Password-protected PDFs and OCR are unsupported.

## Find references online

Open **Discovery** when you have a title, author, or topic rather than an identifier.
Choose an available Provider, enter search conditions, and use its supported year filters and
sorting. Where supported, combine conditions with **AND**, **OR**, or **NOT**; OpenAlex permits
**OR** only between adjacent conditions on the same field.

Selecting a Discovery result prepares it for Import. Review and confirm it before it becomes an
Item. Discovery queries external Providers; [Library Search](/guides/library-management/) searches
content already stored in your Workspace.

## Manage import history

Use Import history to return to a retained preview or a committed batch's imported Items.
Discard an unconfirmed batch to abandon it. Deleting a committed import record keeps its Items and
files, but removes the receipt and the corresponding batch filter in Library.

Batches are temporary and expire according to the installation's retention settings. Import history
is not a permanent backup of your source files. See [maintenance](/administration/maintenance/).
