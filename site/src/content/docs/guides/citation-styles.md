---
title: Choose and share Citation Styles
description: Find a formatting style, install custom CSL XML, and use it for reference exports.
---

A **Citation Style** controls how reference metadata is formatted, including author names, dates,
punctuation, and title styling. Use the Workspace's style catalog to find a suitable format or share
a journal's custom CSL style with colleagues.

## Find a style

1. Open **Tools → Citation Styles** in the Workspace you use for writing.
2. Enter a journal or style name in **Search Citation Styles**.
3. Use **Source** to show **Built-in**, **Custom**, or **All sources**.
4. Use the name sort and pagination controls to browse the matches.

Built-in styles come with the installation's `citation` extra; the Docker image includes it.
Custom styles are shared within the current Workspace. For installation details, see
[optional features](/administration/configuration/).

## Add a custom CSL style

Have the journal's or institution's CSL file ready, then open **Tools → Citation Styles**:

1. Choose **Add custom Citation Style**.
2. Enter a recognizable **Style name**, such as `Lab journal — 2026`.
3. Open the `.csl` file in a text editor and copy its full XML content into **CSL XML**.
4. Choose **Install Citation Style**.
5. Search for the name with **Source → Custom** and check that it appears in the catalog.

Use a distinct name for each custom style. If installation reports invalid CSL, check that the
paste includes the complete XML document from the file. Then retry with the corrected content.

## Make the style your export default

1. Open **Account settings → Export preferences**.
2. Set **Default citation format** to **CSL citation**, then open the **CSL** tab if needed.
3. Under **Workspace for citation style**, choose the Workspace where you found or installed the style.
4. Search for its name and select it under **Default CSL style**.

Changes save as you make them. This browser remembers your preferences for your account, with
the selected style stored per Workspace. Each colleague can choose their preferred style from the
shared catalog.

## Check the formatted result

1. Open a reference with complete author, title, and date metadata, then choose **Export**.
2. Select **CSL citation** and choose **Copy to clipboard** to generate the reference.
3. Inspect **Citation text** or paste the result into your writing tool. Check author order,
   punctuation, capitalization, and journal details against the required format.
4. To try another style, use **Export settings** to change your preference, return to the Item, and
   export again. Use **Download file** if you want a text file of the result.

If an author or date is missing, complete the Item's **Metadata**, then generate the output again.
For a bibliography, repeat the check with a [Library selection](/guides/citations-and-exports/#export-a-library-selection).

A **Citation Key**, such as `smith2026reading`, identifies a reference in formats such as BibTeX.
Edit it in the Item's **Metadata**. Choose a CSL style when you want to change the rendered format.

## Replace or remove a custom style

To introduce a revised style, install it under a distinct name, test its output, and select it in
your export preferences. Colleagues can switch to the new version when ready.

To retire the old style, find it under **Source → Custom**, choose **Delete**, check the name, and
confirm **Delete Style**. This removes that style from the Workspace's shared catalog. Anyone using
it should select a replacement in **Export preferences** before their next CSL export.
