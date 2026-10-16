from __future__ import annotations

from html import escape
from typing import TYPE_CHECKING
from xml.etree import ElementTree

from commonmeta.base_utils import compact

from inquiro.canonical import clean_rich_markup, first_text
from inquiro.identifiers import parse_pmid
from inquiro.models import (
    CandidateNotFound,
    CandidatePage,
    CandidateRecord,
    Identifier,
    ProviderConfig,
    ProviderUnavailable,
    SearchQuery,
)
from inquiro.providers._contracts import ProviderDefinition
from inquiro.providers._payload import (
    ncbi_contributors,
    ncbi_summaries,
    source_affiliation,
    source_credit,
    source_files,
    source_identifiers,
    source_landing_url,
    source_link,
    source_subjects,
    source_work_id,
)

if TYPE_CHECKING:
    from inquiro.transport import BoundedTransport


def _xml_text(node: ElementTree.Element | None) -> str | None:
    return first_text("".join(node.itertext())) if node is not None else None


def _xml_rich(node: ElementTree.Element | None) -> str | None:
    if node is None:
        return None
    return clean_rich_markup(
        escape(node.text or "")
        + "".join(ElementTree.tostring(child, encoding="unicode") for child in node)
    )


def _date(date: ElementTree.Element | None) -> str | None:
    if date is None:
        return None
    year = _xml_text(date.find("Year"))
    if not year:
        return _xml_text(date.find("MedlineDate"))
    month = _xml_text(date.find("Month"))
    if not month or not (month.isdigit() or month.isalpha()):
        return year
    day = _xml_text(date.find("Day"))
    return "-".join(part for part in (year, month, day if day and day.isdigit() else None) if part)


def _authors(document: ElementTree.Element) -> tuple[dict, ...] | None:
    author_lists = [
        node
        for node in document.findall("AuthorList")
        if node.get("Type", "authors").casefold() == "authors"
    ]
    if not author_lists:
        return None
    authors = []
    for author_list in author_lists:
        for node in author_list.findall("Author"):
            organization = _xml_text(node.find("CollectiveName"))
            family = _xml_text(node.find("LastName"))
            given = _xml_text(node.find("ForeName")) or _xml_text(node.find("Initials"))
            suffix = _xml_text(node.find("Suffix"))
            name = organization or " ".join(part for part in (given, family, suffix) if part)
            if not name:
                continue
            identities = tuple(
                Identifier(source.casefold(), identity)
                for item in node.findall("Identifier")
                if (source := item.get("Source")) and (identity := _xml_text(item))
            )
            affiliations = tuple(
                source_affiliation(
                    affiliation_name,
                    identifiers=tuple(
                        Identifier(source.casefold(), identity)
                        for item in info.findall("Identifier")
                        if (source := item.get("Source")) and (identity := _xml_text(item))
                    ),
                )
                for info in node.findall("AffiliationInfo")
                if (affiliation_name := _xml_text(info.find("Affiliation")))
            )
            authors.append(
                source_credit(
                    name,
                    family_name=family,
                    given_name=given,
                    kind="organization" if organization else "person",
                    identifiers=identities,
                    affiliations=affiliations if node.find("AffiliationInfo") is not None else None,
                )
            )
    return tuple(authors) or None


class PubMedLookupAdapter:
    async def lookup(
        self,
        client: BoundedTransport,
        identifier: Identifier,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> CandidateRecord:
        value = identifier.value
        params = {"db": "pubmed", "id": value, "retmode": "xml", "tool": "inquiro"}
        if settings.contact_email:
            params["email"] = settings.contact_email
        if settings.ncbi_api_key:
            params["api_key"] = settings.ncbi_api_key
        body = await client.get(f"{endpoint}/efetch.fcgi", params)
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as error:
            raise ProviderUnavailable("PubMed returned invalid XML") from error
        record = root.find("PubmedArticle")
        if record is not None:
            document = record.find("MedlineCitation")
            article = record.find("MedlineCitation/Article")
            if document is None or article is None:
                raise CandidateNotFound("PubMed record was not found")
            title = _xml_rich(article.find("ArticleTitle"))
            reference_type = "JournalArticle"
            authors = _authors(article)
            publication_date = _date(article.find("Journal/JournalIssue/PubDate"))
            publication_title = _xml_text(article.find("Journal/Title"))
            journal_abbreviation = _xml_text(article.find("Journal/ISOAbbreviation"))
            volume = _xml_text(article.find("Journal/JournalIssue/Volume"))
            issue = _xml_text(article.find("Journal/JournalIssue/Issue"))
            publisher = None
            identifier_nodes = record.findall("PubmedData/ArticleIdList/ArticleId")
        elif (record := root.find("PubmedBookArticle")) is not None:
            document = record.find("BookDocument")
            book = record.find("BookDocument/Book")
            if document is None or book is None:
                raise CandidateNotFound("PubMed record was not found")
            article = document
            chapter_title = _xml_rich(document.find("ArticleTitle"))
            title = chapter_title or _xml_rich(book.find("BookTitle"))
            reference_type = "BookChapter" if chapter_title else "Book"
            authors = _authors(document)
            if authors is None and reference_type == "Book":
                authors = _authors(book)
            publication_date = _date(book.find("PubDate"))
            publication_title = _xml_text(book.find("BookTitle")) if chapter_title else None
            journal_abbreviation = None
            volume = _xml_text(book.find("Volume"))
            issue = None
            publisher = _xml_text(book.find("Publisher/PublisherName"))
            identifier_nodes = document.findall("ArticleIdList/ArticleId") + record.findall(
                "PubmedBookData/ArticleIdList/ArticleId"
            )
        else:
            raise CandidateNotFound("PubMed record was not found")
        if not title:
            raise CandidateNotFound("PubMed record was not found")
        identifiers = []
        doi = None
        for node in identifier_nodes:
            if identity := _xml_text(node):
                namespace = {"pubmed": "pmid", "pmc": "pmcid", "doi": "doi"}.get(
                    node.get("IdType", "")
                )
                if namespace:
                    identifiers.append(Identifier(namespace, identity))
                    if namespace == "doi":
                        doi = identity
        if doi is None:
            doi = next(
                (
                    identity
                    for node in article.findall("ELocationID")
                    if node.get("EIdType") == "doi"
                    and node.get("ValidYN", "Y") == "Y"
                    and (identity := _xml_text(node))
                ),
                None,
            )
            if doi:
                identifiers.append(Identifier("doi", doi))
        pmid = _xml_text(document.find("PMID"))
        if pmid and (not any(identity.provider == "pmid" for identity in identifiers)):
            identifiers.insert(0, Identifier("pmid", pmid))
        abstract = []
        for node in article.findall("Abstract/AbstractText"):
            if content := _xml_rich(node):
                label = first_text(node.get("Label"))
                abstract.append(f"{escape(label)}: {content}" if label else content)
        links = [source_link(f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", kind="landing_page")]
        if doi:
            links.append(source_link(f"https://doi.org/{doi}", kind="landing_page"))
        if pmcid := next(
            (identity.value for identity in identifiers if identity.provider == "pmcid"), None
        ):
            links.append(
                source_link(f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/", kind="landing_page")
            )
        return CandidateRecord(
            provider="pubmed",
            lookup_identifier=identifier,
            work=compact({
                "id": source_work_id(tuple(dict.fromkeys(identifiers))),
                "type": reference_type,
                "title": title,
                "description": " ".join(abstract) or None,
                "contributors": authors,
                "date_published": publication_date,
                "identifiers": source_identifiers(tuple(dict.fromkeys(identifiers))),
                "subjects": source_subjects(
                    (
                        tuple(
                            dict.fromkeys(
                                (
                                    keyword
                                    for node in document.findall("KeywordList/Keyword")
                                    if (keyword := _xml_text(node))
                                )
                            )
                        )
                        if document.find("KeywordList") is not None
                        else None
                    )
                    or ()
                ),
                "publisher": {"name": publisher} if publisher else None,
                "container": compact({
                    "title": publication_title,
                    "volume": volume,
                    "issue": issue,
                    "additional_titles": [journal_abbreviation] if journal_abbreviation else None,
                    "first_page": _xml_text(article.find("Pagination/MedlinePgn")),
                }),
                "url": source_landing_url(tuple(links)),
                "files": source_files(tuple(links)),
            }),
        )


class PubMedSearchAdapter:
    async def search(
        self,
        client: BoundedTransport,
        request: SearchQuery,
        *,
        settings: ProviderConfig,
        endpoint: str,
    ) -> CandidatePage:
        total, summaries = await ncbi_summaries(client, request, settings, endpoint, "pubmed")
        results = []
        for pmid, item in summaries:
            title = clean_rich_markup(item.get("title"))
            if not title:
                continue
            results.append(
                CandidateRecord(
                    provider="pubmed",
                    lookup_identifier=Identifier("pmid", pmid),
                    work=compact({
                        "id": source_work_id((
                            Identifier("pmid", pmid),
                            *(
                                Identifier(namespace, entry["value"])
                                for entry in item.get("articleids", [])
                                if (
                                    namespace := {
                                        "doi": "doi",
                                        "pmc": "pmcid",
                                        "pmcid": "pmcid",
                                    }.get(entry.get("idtype"))
                                )
                                and entry.get("value")
                            ),
                        )),
                        "type": "JournalArticle",
                        "title": title,
                        "contributors": ncbi_contributors(item),
                        "date_published": item.get("pubdate"),
                        "identifiers": source_identifiers((
                            Identifier("pmid", pmid),
                            *(
                                Identifier(namespace, entry["value"])
                                for entry in item.get("articleids", [])
                                if (
                                    namespace := {
                                        "doi": "doi",
                                        "pmc": "pmcid",
                                        "pmcid": "pmcid",
                                    }.get(entry.get("idtype"))
                                )
                                and entry.get("value")
                            ),
                        )),
                        "container": compact({"title": item.get("source")}),
                    }),
                )
            )
        return CandidatePage("pubmed", tuple(results), total, request.page, request.per_page)


PUBMED_PROVIDER = ProviderDefinition(
    name="pubmed",
    display_name="PubMed",
    identifier_namespace="pmid",
    identifier_parser=parse_pmid,
    auto_detect_identifier=True,
    search_adapter=PubMedSearchAdapter(),
    lookup_adapter=PubMedLookupAdapter(),
    endpoint="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
)
