# Import references and search online

Use **Import** to add references from identifiers, bibliography data or PDFs, or enter their
details manually. Use **Discovery** to search online when you have a title, author or topic.

The Import page offers four tabs:

| Tab | What you can add |
| --- | --- |
| Identifiers | Up to 50 DOI, PMID, arXiv, OpenAlex or ISBN identifiers, one per line |
| Bibliography | An uploaded file or pasted BibTeX, RIS, CSL-JSON or Commonmeta data |
| PDFs | Published PDFs, with a preview of the metadata found for each file |
| Manual creation | Reference details entered in the metadata editor |

For identifier lookup, leave the data source on **Auto detect**, or choose a source explicitly.
Supported identifier links, such as DOI and PubMed URLs, can also be pasted. Add the `ISBN:`
prefix to ISBN-10 values so they can be distinguished from PubMed IDs:

```text
10.1073/pnas.92.6.2288
https://pubmed.ncbi.nlm.nih.gov/11607519/
arXiv:2304.08030
ISBN:0674016394
```

Bibliography data must use UTF-8 and be no larger than 5 MiB. The format is detected
automatically; choose it explicitly if detection is ambiguous. EndNote XML and references
copied from a formatted bibliography are not currently supported. Export BibTeX or RIS from
your reference manager instead.

Review the preview before confirming an import. References are saved only after confirmation.
If some entries fail, the preview shows which ones need attention while keeping the successful
entries available. Refreshing the preview page preserves the prepared references.

Online search supports fielded queries, publication-year limits, sorting and multiple result
pages. Available options depend on the selected source. Where supported, combine conditions
with **AND**, **OR** or **NOT**. OpenAlex permits **OR** only between adjacent conditions on the
same field. Select a result to review its details before adding it.

Sources include Crossref, DataCite, Commonmeta, PubMed, PMC, arXiv, OpenAlex, Open Library,
NASA ADS and IEEE Xplore. Their lookup and search capabilities differ; the choices shown in
the interface reflect what is available. PMC supports online search, but PMCID lookup is not
currently supported. Some sources require administrator configuration before they can be used.

General website and article landing-page URLs are not currently supported for metadata lookup.
Use a supported identifier or enter the reference manually. Metadata from online sources may
be incomplete, so check titles, contributors and publication details before saving.
