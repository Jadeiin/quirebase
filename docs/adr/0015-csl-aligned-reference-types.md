---
status: accepted
---

# ADR 0015: use CSL-aligned Reference Types with directional format mappings

Quirebase imports multiple bibliography formats and renders CSL citations. Reference Types use
CSL's semantic names rather than BibTeX entry types, while Item storage remains Quirebase's
domain model. Inquiro selects its supported subset from citeproc-py's bundled CSL schema.
Inquiro owns one shared enum and the source-aware mappings; Models uses that enum
for its non-native SQLAlchemy constraint, and the generated HTTP schema supplies frontend choices.

The supported scholarly subset includes general, journal, magazine and newspaper articles,
books, chapters, conference papers, theses, reports, datasets, software, webpages, patents,
standards, manuscripts and documents. The existing preprint classification remains a Library
extension, follows the standard types in the enum and projects as CSL article. Degree and
publication status do not create extra types or new metadata fields.

Mapping rules are curated from the [CSL input schema](https://github.com/citation-style-language/schema/blob/master/schemas/input/csl-data.json)
and Citation.js's [BibTeX](https://github.com/citation-js/citation-js/blob/main/packages/plugin-bibtex/src/mapping/bibtexTypes.json),
[BibLaTeX](https://github.com/citation-js/citation-js/blob/main/packages/plugin-bibtex/src/mapping/biblatexTypes.json)
and [RIS](https://github.com/citation-js/citation-js/blob/main/packages/plugin-ris/src/spec/types.json)
tables. They are maintained locally and tested through imports and exports, without a new
conversion dependency. citeproc-py is a base Inquiro dependency; the style catalog remains in
the citation extra. Quirebase supports EndNote tagged files, not EndNote XML numeric codes.

Import and export directions are explicit. BibTeX article means journal article; CSL article
retains its general meaning. BibTeX proceedings, RIS CONF and EndNote Conference Proceedings
describe whole volumes and map to book; inproceedings, CPAPER and Conference Paper map to
paper-conference. RIS INPR remains article-journal without encoding publication status, and STAND
maps to standard. A thesis with no degree exports as BibTeX misc, avoiding an invented PhD;
BibLaTeX, RIS, EndNote and CSL retain the thesis classification.

Unsupported source classifications become document. File imports retain their original type and
format in existing custom fields and report a warning that does not prevent confirmation. Parse
and validation errors retain their blocking behavior. Format limitations can still make export
lossy; the supported subset and its deliberate losses are covered by conversion tests.
