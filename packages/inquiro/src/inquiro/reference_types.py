"""Reference Type vocabulary and directional external-format mappings.

The supported types follow CSL-JSON, with preprint retained for Library use.
Mappings are curated from CSL's input schema and Citation.js's BibTeX,
BibLaTeX and RIS tables; they are deliberately not reversed for export.
"""

from __future__ import annotations

from enum import StrEnum
from xml.etree import ElementTree

from citeproc import SCHEMA_PATH

_CSL_TYPES = {
    node.text: node.text
    for node in ElementTree.parse(SCHEMA_PATH).findall(
        ".//{http://relaxng.org/ns/structure/1.0}define[@name='item-types']"
        "//{http://relaxng.org/ns/structure/1.0}value"
    )
    if node.text
}


class ReferenceType(StrEnum):
    article = _CSL_TYPES["article"]
    article_journal = _CSL_TYPES["article-journal"]
    article_magazine = _CSL_TYPES["article-magazine"]
    article_newspaper = _CSL_TYPES["article-newspaper"]
    book = _CSL_TYPES["book"]
    chapter = _CSL_TYPES["chapter"]
    paper_conference = _CSL_TYPES["paper-conference"]
    thesis = _CSL_TYPES["thesis"]
    report = _CSL_TYPES["report"]
    webpage = _CSL_TYPES["webpage"]
    dataset = _CSL_TYPES["dataset"]
    software = _CSL_TYPES["software"]
    patent = _CSL_TYPES["patent"]
    standard = _CSL_TYPES["standard"]
    manuscript = _CSL_TYPES["manuscript"]
    document = _CSL_TYPES["document"]
    preprint = "preprint"


_BIBTEX_TYPES = {
    "article": ReferenceType.article_journal,
    "book": ReferenceType.book,
    "booklet": ReferenceType.book,
    "conference": ReferenceType.paper_conference,
    "inbook": ReferenceType.chapter,
    "incollection": ReferenceType.chapter,
    "inproceedings": ReferenceType.paper_conference,
    "manual": ReferenceType.report,
    "mastersthesis": ReferenceType.thesis,
    "misc": ReferenceType.document,
    "phdthesis": ReferenceType.thesis,
    "proceedings": ReferenceType.book,
    "techreport": ReferenceType.report,
    "unpublished": ReferenceType.manuscript,
    "report": ReferenceType.report,
    "thesis": ReferenceType.thesis,
}
_IMPORT_TYPES = {
    "internal": {member.value: member for member in ReferenceType},
    "bibtex": _BIBTEX_TYPES,
    "biblatex": {
        **_BIBTEX_TYPES,
        "mvbook": ReferenceType.book,
        "bookinbook": ReferenceType.book,
        "collection": ReferenceType.book,
        "mvcollection": ReferenceType.book,
        "mvproceedings": ReferenceType.book,
        "reference": ReferenceType.book,
        "mvreference": ReferenceType.book,
        "dataset": ReferenceType.dataset,
        "software": ReferenceType.software,
        "online": ReferenceType.webpage,
        "electronic": ReferenceType.webpage,
        "www": ReferenceType.webpage,
        "patent": ReferenceType.patent,
        "report": ReferenceType.report,
        "standard": ReferenceType.standard,
        "thesis": ReferenceType.thesis,
    },
    "ris": {
        "jour": ReferenceType.article_journal,
        "ejour": ReferenceType.article_journal,
        "abst": ReferenceType.article_journal,
        "inpr": ReferenceType.article_journal,
        "mgzn": ReferenceType.article_magazine,
        "news": ReferenceType.article_newspaper,
        "book": ReferenceType.book,
        "ebook": ReferenceType.book,
        "edbook": ReferenceType.book,
        "chap": ReferenceType.chapter,
        "echap": ReferenceType.chapter,
        # CONF describes a proceedings volume; CPAPER describes a single paper.
        "conf": ReferenceType.book,
        "cpaper": ReferenceType.paper_conference,
        "data": ReferenceType.dataset,
        "dbase": ReferenceType.dataset,
        "aggr": ReferenceType.dataset,
        "comp": ReferenceType.software,
        "gen": ReferenceType.document,
        "pat": ReferenceType.patent,
        "rprt": ReferenceType.report,
        "govdoc": ReferenceType.report,
        "thes": ReferenceType.thesis,
        "elec": ReferenceType.webpage,
        "web": ReferenceType.webpage,
        "stand": ReferenceType.standard,
        "manscpt": ReferenceType.manuscript,
        "unpb": ReferenceType.manuscript,
    },
    "endnote": {
        "journal-article": ReferenceType.article_journal,
        "magazine-article": ReferenceType.article_magazine,
        "newspaper-article": ReferenceType.article_newspaper,
        "book": ReferenceType.book,
        "edited-book": ReferenceType.book,
        "book-section": ReferenceType.chapter,
        "book-chapter": ReferenceType.chapter,
        "conference-proceedings": ReferenceType.book,
        "conference-paper": ReferenceType.paper_conference,
        "thesis": ReferenceType.thesis,
        "dissertation": ReferenceType.thesis,
        "report": ReferenceType.report,
        "web-page": ReferenceType.webpage,
        "dataset": ReferenceType.dataset,
        "computer-program": ReferenceType.software,
        "patent": ReferenceType.patent,
        "standard": ReferenceType.standard,
        "unpublished-work": ReferenceType.manuscript,
        "manuscript": ReferenceType.manuscript,
        "preprint": ReferenceType.preprint,
        "generic": ReferenceType.document,
    },
    "crossref": {
        "journal-article": ReferenceType.article_journal,
        "book": ReferenceType.book,
        "monograph": ReferenceType.book,
        "edited-book": ReferenceType.book,
        "reference-book": ReferenceType.book,
        "book-chapter": ReferenceType.chapter,
        "book-section": ReferenceType.chapter,
        "book-part": ReferenceType.chapter,
        "proceedings": ReferenceType.book,
        "proceedings-article": ReferenceType.paper_conference,
        "posted-content": ReferenceType.preprint,
        "dissertation": ReferenceType.thesis,
        "report": ReferenceType.report,
        "report-component": ReferenceType.report,
        "dataset": ReferenceType.dataset,
        "standard": ReferenceType.standard,
    },
    "datacite": {
        "journalarticle": ReferenceType.article_journal,
        "datapaper": ReferenceType.article_journal,
        "book": ReferenceType.book,
        "bookchapter": ReferenceType.chapter,
        "conferencepaper": ReferenceType.paper_conference,
        "conferenceproceeding": ReferenceType.book,
        "dissertation": ReferenceType.thesis,
        "report": ReferenceType.report,
        "dataset": ReferenceType.dataset,
        "software": ReferenceType.software,
        "standard": ReferenceType.standard,
        "preprint": ReferenceType.preprint,
        "text": ReferenceType.document,
        "other": ReferenceType.document,
    },
    "ieee": {
        "journals": ReferenceType.article_journal,
        "conferences": ReferenceType.paper_conference,
        "books": ReferenceType.chapter,
        "standards": ReferenceType.standard,
    },
    "nasa_ads": {
        "article": ReferenceType.article_journal,
        "inproceedings": ReferenceType.paper_conference,
        "proceedings": ReferenceType.book,
        "book": ReferenceType.book,
        "inbook": ReferenceType.chapter,
        "phdthesis": ReferenceType.thesis,
        "mastersthesis": ReferenceType.thesis,
        "eprint": ReferenceType.preprint,
        "catalog": ReferenceType.dataset,
        "software": ReferenceType.software,
        "misc": ReferenceType.document,
    },
    "openalex": {
        "article": ReferenceType.article_journal,
        "review": ReferenceType.article_journal,
        "editorial": ReferenceType.article_journal,
        "letter": ReferenceType.article_journal,
        "erratum": ReferenceType.article_journal,
        "book": ReferenceType.book,
        "book-chapter": ReferenceType.chapter,
        "dissertation": ReferenceType.thesis,
        "preprint": ReferenceType.preprint,
        "report": ReferenceType.report,
        "dataset": ReferenceType.dataset,
        "standard": ReferenceType.standard,
        "software": ReferenceType.software,
    },
}

# Explicit export choices: BibTeX, BibLaTeX, RIS, EndNote tagged.
# BibTeX has no degree-neutral thesis entry; misc avoids claiming a PhD.
_EXPORT_TYPES = {
    ReferenceType.article: ("article", "article", "GEN", "Generic"),
    ReferenceType.article_journal: ("article", "article", "JOUR", "Journal Article"),
    ReferenceType.article_magazine: ("article", "article", "MGZN", "Magazine Article"),
    ReferenceType.article_newspaper: ("article", "article", "NEWS", "Newspaper Article"),
    ReferenceType.book: ("book", "book", "BOOK", "Book"),
    ReferenceType.chapter: ("incollection", "incollection", "CHAP", "Book Section"),
    ReferenceType.paper_conference: (
        "inproceedings",
        "inproceedings",
        "CPAPER",
        "Conference Paper",
    ),
    ReferenceType.preprint: ("misc", "article", "UNPB", "Preprint"),
    ReferenceType.thesis: ("misc", "thesis", "THES", "Thesis"),
    ReferenceType.report: ("techreport", "report", "RPRT", "Report"),
    ReferenceType.webpage: ("misc", "online", "ELEC", "Web Page"),
    ReferenceType.dataset: ("misc", "dataset", "DATA", "Dataset"),
    ReferenceType.software: ("misc", "software", "COMP", "Computer Program"),
    ReferenceType.patent: ("misc", "patent", "PAT", "Patent"),
    ReferenceType.standard: ("misc", "standard", "STAND", "Standard"),
    ReferenceType.manuscript: ("unpublished", "unpublished", "MANSCPT", "Unpublished Work"),
    ReferenceType.document: ("misc", "misc", "GEN", "Generic"),
}


def normalize_reference_type(
    value: str | None,
    *,
    source: str = "internal",
    default: ReferenceType | None = ReferenceType.document,
) -> ReferenceType | None:
    """Map a source classification; missing input stays missing.

    Pass default=None to detect unsupported input before falling back to document.
    Source matters: BibTeX article is a journal article, CSL article is not.
    """
    if not value or not value.strip():
        return None
    key = value.strip().casefold().replace("_", "-").replace(" ", "-")
    return _IMPORT_TYPES[source].get(key, default)


def export_reference_type(value: str | None, target: str) -> str:
    reference_type = normalize_reference_type(value) or ReferenceType.document
    if target == "csl":
        return (
            ReferenceType.article.value
            if reference_type == ReferenceType.preprint
            else reference_type.value
        )
    column = ("bibtex", "biblatex", "ris", "endnote").index(target)
    return _EXPORT_TYPES[reference_type][column]
