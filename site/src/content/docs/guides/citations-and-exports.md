---
title: Export references, citations, and document bundles
description: Choose formats and Citation Styles, configure browser defaults, and export the intended selection.
---

## Choose the output you need

| Output | Use it for |
| --- | --- |
| BibTeX | References for a BibTeX-based writing workflow |
| RIS | Bibliography interchange with a reference manager |
| CSL-JSON | Structured citation metadata for CSL-aware tools |
| Commonmeta | The complete Work metadata interchange value |
| Formatted bibliography | Citation Style-based text for copying into writing |
| Document bundle | Selected PDFs and optional supplementary content |

These exports operate on Items visible to you. A bibliography file is not a backup of the database,
Workspace membership, Discussions, or all research files. Operators should use the separate
[backup procedure](/administration/maintenance/#back-up-and-restore-local-object-storage).

## Set browser defaults

Open **Account settings → Export preferences**. Choose the default format, sorting, abstract
inclusion, DOI/URL policy, and applicable format-specific options. Field exclusions apply only to
BibTeX and CSL-JSON; required identity and type fields remain. Commonmeta exports retain all metadata,
including abstracts and identifiers.

Defaults are stored in the current browser rather than synchronized as server-side preferences.
The selected CSL Citation Style is also specific to the Workspace context. Recheck your choices
when using another browser, device, or Workspace.

## Export a reference or selection

1. For one Item, open **Export**. For a Library selection, check the selected Items before opening
   the available export action.
2. Choose the format and inspect the presented options. Use **Change options** or **Export settings**
   if the defaults do not match this task.
3. Choose **Download file** or **Copy to clipboard**, as appropriate.
4. Check the result in your writing tool, including Contributor order, publication details, and
   Citation Keys.

If clipboard access is denied, copy the displayed citation text manually or download the file.
Filtering Library or navigating to another page can change what you are acting on; verify the
selected set before exporting.

## Choose a Citation Style

Use an available CSL style for formatted citations. In **Tools → Citation Styles**, search the
built-in catalog and the custom styles shared in the Workspace. Operators can install the optional
`citation` extra for built-in styles; authorized members can add custom CSL styles without it.

A Citation Key is an editable Item property, distinct from a Citation Style. A key names the Item in
citation output; a style controls the formatted bibliography. Changing the generation formula in
browser preferences does not by itself rewrite every stored Item's Citation Key.

## Download PDFs with the intended context

Use an Item's **Download** action to choose PDF revisions for a document bundle. Review whether the
current preferences include Annotations and supplements before downloading. A new revision does not
inherit marks from another revision.

For one PDF and an explicit set of displayed annotation sources, use the
[reader's download menu](/guides/pdf-annotations/#download-a-pdf). Annotation exports leave the stored
source unchanged and expire independently of the Item.
