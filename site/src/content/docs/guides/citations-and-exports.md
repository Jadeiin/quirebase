---
title: Export references and document bundles
description: Pick the correct citation format, export a known selection, and verify browser-specific defaults.
---

Use this guide after the references are saved in Library. Choose the intended Workspace and check
which Items are selected before opening an export action.

## Choose an output

| Output | Choose it for | What it contains |
| --- | --- | --- |
| CSL citation | Copying a formatted bibliography into writing | Text rendered with an available CSL Citation Style |
| BibTeX | A BibTeX-based writing workflow | Bibliography data, including Citation Keys |
| RIS | Transfer to a reference manager | Interchange reference data |
| CSL-JSON | CSL-aware tools or structured interchange | Citation metadata in JSON |
| Commonmeta | Complete bibliographic metadata interchange | Structured metadata, including abstracts and identifiers |
| Document bundle | Downloading research files | Selected PDF revisions and optional supplementary content |

## Export one Item

1. Open the Item and choose **Export**.
2. In the citation action, choose **Format**. For a formatted bibliography, choose **CSL citation**;
   for a reference-manager import, choose a supported interchange format.
3. Review the displayed text and options. Use **Change options** or **Export settings** when needed.
4. Choose **Copy to clipboard** or **Download file**.
5. Open the result in the destination tool and check the Contributor order, dates, title, and Citation Key.

If clipboard access is denied, copy the displayed **Citation text** manually or download the file.

## Export a Library selection

Select the intended Library rows, then use a bibliography or document action. **Select this page**
selects the current page. Check the selected count before exporting.

To export a Project's references, first open its working set in Library and check the Project filter,
then select the intended records. Project filtering chooses records; the export format chooses how
their metadata is represented.

## Set defaults for this browser

Open **Account settings → Export preferences**:

1. Set the default citation format and, for CSL output, choose a Citation Style from an accessible
   Workspace's catalog.
2. Review sorting, abstract inclusion, DOI/URL policy, and format-specific options.
3. For document bundles, check whether Annotations and supplements should be included.
4. Return to the export action and inspect the resulting choices before downloading.

Preferences are stored in this browser for your account. Citation Style selection is also scoped to
the Workspace. Set your preferred defaults here when using a new browser or device.

Field exclusions apply to BibTeX and CSL-JSON; required identity/type fields remain. Commonmeta
exports retain all metadata.

## Find or add a Citation Style

Open **Tools → Citation Styles** to search built-in and Workspace custom styles. Built-in styles
require the operator's optional `citation` extra. Users with style-management permission can upload
custom CSL styles for the Workspace.

A **Citation Key** identifies the Item in citation output. A **Citation Style** controls formatting.

## Download the right PDF context

Use the Item's **Download** action to choose PDF revisions and **Download bundle**. Review the shown
Annotation/supplement preferences. For one PDF and an explicit set of displayed annotation sources,
use the [reader's Download menu](/guides/pdf-annotations/#download-a-pdf).

**Check the result:** the archive or PDF contains the intended revision and Annotation sources.
