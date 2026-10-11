from __future__ import annotations

from types import SimpleNamespace

import httpx2
import pytest
from inquiro import Identifier
from inquiro.bibliography import BibliographyRecord, record_to_csl_json
from inquiro.canonical import normalize_publication_date
from inquiro_provider_helpers import provider_runtime

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("2024", "2024"),
        ("2024-02", "2024-02"),
        ("2024-02-29", "2024-02-29"),
        ("2024-02-29T12:00:00Z", "2024-02-29"),
        ("2024-02-29T12:00:00+0500", "2024-02-29"),
        ("Oct 23, 2020", "2020-10-23"),
        ("2020 Oct 23", "2020-10-23"),
        ("August 1988", "1988-08"),
        ("2020 Jan-Feb", "2020"),
        ("2020 Jan 2-3", "2020-01"),
        ("2020 Jan 2\u20133", "2020-01"),
        ("2020 Jan 2-Jan 3", "2020-01"),
        ("2020 Jan 2-Feb 3", "2020"),
        ("2020 Dec 31-2021 Jan 1", None),
        ("2020-01-02/2020-01-03", "2020-01"),
        ("2020-01/2020-02", "2020"),
        ("2020-2021", None),
        ("2020-01-00", "2020-01"),
        ("2020-00-00", "2020"),
        ("2020-02-30", "2020-02"),
        ("2020-13-01", "2020"),
        ("Spring 2020", "2020"),
        ("unknown", None),
    ],
)
def test_upstream_dates_preserve_only_the_available_precision(source, expected):
    assert normalize_publication_date(source) == expected


@pytest.mark.parametrize(
    ("publication_date", "issued"),
    [
        ("2020-02-30", {"date-parts": [[2020, 2]]}),
        ("2020-01-02/2020-01-03", {"date-parts": [[2020, 1]]}),
        ("2020 Dec 31-2021 Jan 1", None),
    ],
)
def test_csl_projection_uses_the_same_date_precision_contract(publication_date, issued):
    bibliography = BibliographyRecord(
        citation_key="date",
        reference_type="article-journal",
        title="Publication precision",
        publication_date=publication_date,
    )
    assert record_to_csl_json(bibliography).get("issued") == issued


async def test_datacite_preserves_explicit_names_organizations_and_subject_boundaries():
    payload = {
        "data": {
            "attributes": {
                "doi": "10.1000/structured",
                "titles": [{"title": "Structured names"}],
                "creators": [
                    {"name": "World Health Organization", "nameType": "Organizational"},
                    {
                        "name": "Display name",
                        "familyName": "de la Cruz",
                        "givenName": "Juan",
                        "nameType": "Personal",
                        "nameIdentifiers": [
                            {
                                "nameIdentifierScheme": "ORCID",
                                "nameIdentifier": "https://orcid.org/0000-0002-1825-0097",
                            }
                        ],
                        "affiliation": [
                            {
                                "name": "Example University",
                                "affiliationIdentifier": "https://ror.org/03yrm5c26",
                                "affiliationIdentifierScheme": "ROR",
                            }
                        ],
                    },
                ],
                "subjects": [{"subject": "Alpha; beta"}, {"subject": "Alpha; beta"}],
                "publisher": "Example Publisher",
            }
        }
    }
    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=payload))
    ) as runtime:
        record = await runtime.lookup("10.1000/structured", provider="datacite")

    organization, person = record.authors
    assert organization.kind == "organization"
    assert organization.bibliographic_name.family_name == "World Health Organization"
    assert organization.bibliographic_name.given_name is None
    assert (person.family_name, person.given_name) == ("de la Cruz", "Juan")
    assert person.bibliographic_name.display_name() == "de la Cruz, Juan"
    assert person.identifiers == (Identifier("orcid", "https://orcid.org/0000-0002-1825-0097"),)
    assert person.affiliations[0].identifiers == (Identifier("ror", "https://ror.org/03yrm5c26"),)
    assert record.keywords == ("Alpha; beta",)
    assert record.publisher == "Example Publisher"
    assert record.publication_title is None


async def test_openalex_preserves_authorship_affiliation_mapping_and_pdf_metadata():
    payload = {
        "id": "https://openalex.org/W123",
        "display_name": "Authorships",
        "authorships": [
            {
                "author": {
                    "display_name": "Ada Lovelace",
                    "id": "https://openalex.org/A123",
                    "orcid": "https://orcid.org/0000-0002-1825-0097",
                },
                "is_corresponding": True,
                "institutions": [
                    {
                        "id": "https://openalex.org/I123",
                        "display_name": "Example University",
                        "ror": "https://ror.org/03yrm5c26",
                        "country_code": "GB",
                    }
                ],
                "affiliations": [
                    {
                        "raw_affiliation_string": "Research Lab, Example University",
                        "institution_ids": ["https://openalex.org/I123"],
                    }
                ],
                "raw_affiliation_strings": ["Research Lab, Example University"],
            },
            {
                "author": {"display_name": "Grace Hopper"},
                "raw_affiliation_strings": ["Other Institute"],
            },
            {
                "author": {"display_name": "Katherine Johnson"},
                "institutions": [{"display_name": "Research Institute", "country_code": "US"}],
            },
        ],
        "primary_location": {
            "landing_page_url": "https://example.test/article",
            "pdf_url": "https://example.test/download?format=pdf",
            "license": "cc-by",
            "version": "publishedVersion",
            "is_oa": True,
        },
    }
    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=payload))
    ) as runtime:
        record = await runtime.lookup("W123", provider="openalex")

    ada, grace, katherine = record.authors
    assert ada.family_name is None and ada.given_name is None
    assert ada.bibliographic_name.family_name == "Lovelace"
    assert ada.is_corresponding is True and grace.is_corresponding is None
    assert ada.affiliations[0].name == "Example University"
    assert ada.affiliations[0].raw_name == "Research Lab, Example University"
    assert ada.affiliations[0].identifiers == (
        Identifier("openalex", "https://openalex.org/I123"),
        Identifier("ror", "https://ror.org/03yrm5c26"),
    )
    assert grace.affiliations[0].name == "Other Institute"
    assert katherine.affiliations[0].name == "Research Institute"
    assert katherine.affiliations[0].identifiers == ()
    assert katherine.affiliations[0].country_code == "US"
    assert len(ada.affiliations) == 1
    pdf = next(link for link in record.urls if link.kind == "full_text")
    assert pdf.media_type == "application/pdf"
    assert (pdf.version, pdf.license, pdf.is_open_access) == ("publishedVersion", "cc-by", True)


async def test_crossref_keeps_link_purpose_and_version_without_guessing_media_type():
    payload = {
        "message": {
            "title": ["Links"],
            "DOI": "10.1000/links",
            "link": [
                {
                    "URL": "https://example.test/download",
                    "content-type": "application/pdf",
                    "content-version": "vor",
                    "intended-application": "text-mining",
                },
                {"URL": "https://example.test/unknown.pdf"},
            ],
        }
    }
    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=payload))
    ) as runtime:
        record = await runtime.lookup("10.1000/links")
    pdf, unknown = [link for link in record.urls if link.kind == "full_text"]
    assert (pdf.media_type, pdf.version, pdf.intended_application) == (
        "application/pdf",
        "vor",
        "text-mining",
    )
    assert unknown.media_type is None


async def test_pubmed_fetch_returns_complete_names_collectives_and_affiliations():
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
    <ArticleTitle>Names with <i>structure</i></ArticleTitle>
    <Journal><Title>Journal</Title><JournalIssue><PubDate><Year>2025</Year><Month>Oct</Month><Day>9</Day></PubDate></JournalIssue></Journal>
    <ELocationID EIdType="pii">S1234-5678(25)00123-4</ELocationID>
    <AuthorList><Author><LastName>de la Cruz</LastName><ForeName>Juan</ForeName><Identifier Source="ORCID">0000-0002-1825-0097</Identifier><AffiliationInfo><Affiliation>Example University</Affiliation><Identifier Source="ROR">https://ror.org/03yrm5c26</Identifier></AffiliationInfo></Author>
    <Author><CollectiveName>World Health Organization</CollectiveName></Author></AuthorList>
    <Abstract><AbstractText Label="RESULTS">Preserved <sup>2</sup></AbstractText></Abstract>
    </Article><KeywordList><Keyword>Alpha; beta</Keyword></KeywordList></MedlineCitation>
    <PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/pubmed</ArticleId><ArticleId IdType="pmc">PMC123</ArticleId></ArticleIdList></PubmedData>
    </PubmedArticle></PubmedArticleSet>"""

    def response(request):
        assert request.url.path.endswith("efetch.fcgi")
        assert request.url.params["retmode"] == "xml"
        return httpx2.Response(200, text=xml)

    async with provider_runtime(transport=httpx2.MockTransport(response)) as runtime:
        record = await runtime.lookup("42", provider="pubmed")
    person, organization = record.authors
    assert (person.family_name, person.given_name) == ("de la Cruz", "Juan")
    assert person.display_name == "Juan de la Cruz"
    assert person.affiliations[0].name == "Example University"
    assert person.affiliations[0].identifiers == (Identifier("ror", "https://ror.org/03yrm5c26"),)
    assert organization.kind == "organization"
    assert record.title == "Names with <i>structure</i>"
    assert record.abstract == "RESULTS: Preserved <sup>2</sup>"
    assert record.publication_date == "2025-10-09"
    assert record.pages is None
    assert record.keywords == ("Alpha; beta",)
    assert Identifier("pmcid", "PMC123") in record.identifiers


@pytest.mark.parametrize(
    ("validity", "listed_doi", "expected"),
    [
        ('ValidYN="Y"', None, "10.1000/elocation"),
        ("", None, "10.1000/elocation"),
        ('ValidYN="N"', None, None),
        ('ValidYN="Y"', "10.1000/listed", "10.1000/listed"),
    ],
)
async def test_pubmed_uses_valid_elocation_doi_when_article_id_is_missing(
    validity, listed_doi, expected
):
    ids = (
        f'<PubmedData><ArticleIdList><ArticleId IdType="doi">{listed_doi}</ArticleId>'
        "</ArticleIdList></PubmedData>"
        if listed_doi
        else ""
    )
    xml = f"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
    <ArticleTitle>ELocation DOI</ArticleTitle>
    <ELocationID EIdType="pii" ValidYN="Y">S123</ELocationID>
    <ELocationID EIdType="doi" {validity}>10.1000/elocation</ELocationID>
    </Article></MedlineCitation>{ids}</PubmedArticle></PubmedArticleSet>"""
    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=xml))
    ) as runtime:
        record = await runtime.lookup("42", provider="pubmed")
    assert record.doi == expected
    assert [identity.value for identity in record.identifiers if identity.provider == "doi"] == (
        [expected] if expected else []
    )
    assert [link.url for link in record.urls if link.url.startswith("https://doi.org/")] == (
        [f"https://doi.org/{expected}"] if expected else []
    )
    bibliography = BibliographyRecord(
        citation_key="elocation",
        reference_type="article-journal",
        title=record.title,
        doi=record.doi,
    )
    assert record_to_csl_json(bibliography).get("DOI") == expected


async def test_pubmed_preserves_xml_literal_text_and_true_inline_markup():
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
    <ArticleTitle>List&lt;T&gt; &amp; &lt;i&gt;literal&lt;/i&gt; <i>real &lt;tag&gt;</i> tail &lt;U&gt;</ArticleTitle>
    <Abstract><AbstractText Label="RESULTS &lt;i&gt;literal&lt;/i&gt;">List&lt;T&gt; &amp; &lt;i&gt;literal&lt;/i&gt; <sup>2</sup> tail &lt;U&gt;</AbstractText></Abstract>
    </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""

    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=xml))
    ) as runtime:
        record = await runtime.lookup("42", provider="pubmed")

    assert record.title == (
        "List&lt;T&gt; &amp; &lt;i&gt;literal&lt;/i&gt; <i>real &lt;tag&gt;</i> tail &lt;U&gt;"
    )
    assert record.abstract == (
        "RESULTS &lt;i&gt;literal&lt;/i&gt;: "
        "List&lt;T&gt; &amp; &lt;i&gt;literal&lt;/i&gt; <sup>2</sup> tail &lt;U&gt;"
    )


@pytest.mark.parametrize(
    ("month", "day", "expected"),
    [("1-2", "", "2025"), ("Jan-Feb", "", "2025"), ("Feb", "2-3", "2025-02")],
)
async def test_pubmed_date_components_do_not_turn_ranges_into_single_dates(month, day, expected):
    xml = f"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
    <ArticleTitle>Date ranges</ArticleTitle><Journal><JournalIssue><PubDate>
    <Year>2025</Year><Month>{month}</Month><Day>{day}</Day>
    </PubDate></JournalIssue></Journal></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=xml))
    ) as runtime:
        record = await runtime.lookup("42", provider="pubmed")
    assert record.publication_date == expected


@pytest.mark.parametrize(
    ("medline_date", "expected", "issued"),
    [
        ("2020 Jan 2-3", "2020-01", {"date-parts": [[2020, 1]]}),
        ("2020 Jan 2-Feb 3", "2020", {"date-parts": [[2020]]}),
        ("2020 Dec 31-2021 Jan 1", None, None),
    ],
)
async def test_pubmed_medline_date_ranges_preserve_common_precision(medline_date, expected, issued):
    xml = f"""<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
    <ArticleTitle>Date ranges</ArticleTitle><Journal><JournalIssue><PubDate>
    <MedlineDate>{medline_date}</MedlineDate>
    </PubDate></JournalIssue></Journal></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=xml))
    ) as runtime:
        record = await runtime.lookup("42", provider="pubmed")
    assert record.publication_date == expected
    bibliography = BibliographyRecord(
        citation_key="range",
        reference_type=record.reference_type,
        title=record.title,
        publication_date=record.publication_date,
    )
    assert record_to_csl_json(bibliography).get("issued") == issued


@pytest.mark.parametrize("is_chapter", [True, False])
@pytest.mark.parametrize("has_pubmed_data", [True, False])
async def test_pubmed_book_fetch_preserves_record_type_and_author_roles(
    is_chapter, has_pubmed_data
):
    chapter = (
        """<ArticleTitle>Chapter <i>title</i></ArticleTitle>
    <Pagination><MedlinePgn>12-18</MedlinePgn></Pagination>
    <AuthorList Type="editors"><Author><LastName>Chapter editor</LastName></Author></AuthorList>
    <AuthorList Type="authors"><Author><LastName>de la Cruz</LastName><ForeName>Juan</ForeName>
    <Identifier Source="ORCID">0000-0002-1825-0097</Identifier>
    <AffiliationInfo><Affiliation>Example University</Affiliation></AffiliationInfo>
    </Author></AuthorList>"""
        if is_chapter
        else ""
    )
    data = (
        """<PubmedBookData><PublicationStatus>epublish</PublicationStatus><ArticleIdList>
    <ArticleId IdType="pubmed">43</ArticleId><ArticleId IdType="doi">10.1000/book-record</ArticleId>
    </ArticleIdList></PubmedBookData>"""
        if has_pubmed_data
        else ""
    )
    xml = f"""<PubmedArticleSet><PubmedBookArticle><BookDocument><PMID>43</PMID>
    <ArticleIdList><ArticleId IdType="pubmed">43</ArticleId>
    <ArticleId IdType="doi">10.1000/book-record</ArticleId></ArticleIdList>
    <Book><Publisher><PublisherName>Example Press</PublisherName></Publisher>
    <BookTitle>Book <i>title</i></BookTitle><PubDate><Year>2024</Year><Month>Feb</Month></PubDate>
    <AuthorList Type="editors"><Author><LastName>Book editor</LastName></Author></AuthorList>
    <AuthorList Type="authors"><Author><LastName>Writer</LastName><ForeName>Ada</ForeName></Author></AuthorList>
    <Volume>2</Volume><Isbn>9780131103627</Isbn></Book>{chapter}
    <Abstract><AbstractText Label="SUMMARY">Book <sup>2</sup> summary</AbstractText></Abstract>
    <KeywordList><Keyword>Alpha; beta</Keyword></KeywordList></BookDocument>{data}
    </PubmedBookArticle></PubmedArticleSet>"""

    def response(request):
        assert request.url.path.endswith("efetch.fcgi")
        assert request.url.params["id"] == "43"
        return httpx2.Response(200, text=xml)

    async with provider_runtime(transport=httpx2.MockTransport(response)) as runtime:
        record = await runtime.lookup("43", provider="pubmed")
    assert record.provider == "pubmed"
    assert record.lookup_identifier == Identifier("pmid", "43")
    assert record.reference_type == ("chapter" if is_chapter else "book")
    assert record.title == ("Chapter <i>title</i>" if is_chapter else "Book <i>title</i>")
    assert record.publication_date == "2024-02"
    assert record.publication_title == ("Book title" if is_chapter else None)
    assert record.publisher == "Example Press"
    assert record.volume == "2"
    assert record.pages == ("12-18" if is_chapter else None)
    assert record.abstract == "SUMMARY: Book <sup>2</sup> summary"
    assert record.keywords == ("Alpha; beta",)
    assert record.doi == "10.1000/book-record"
    assert Identifier("pmid", "43") in record.identifiers
    assert Identifier("doi", "10.1000/book-record") in record.identifiers
    assert len(record.identifiers) == len(set(record.identifiers))
    assert record.urls[0].url == "https://pubmed.ncbi.nlm.nih.gov/43/"
    assert len(record.authors) == 1
    author = record.authors[0]
    assert author.kind == "person"
    if is_chapter:
        assert (author.family_name, author.given_name) == ("de la Cruz", "Juan")
        assert author.identifiers == (Identifier("orcid", "0000-0002-1825-0097"),)
        assert author.affiliations[0].name == "Example University"
    else:
        assert (author.family_name, author.given_name) == ("Writer", "Ada")


async def test_ieee_uses_declared_pdf_links_and_author_affiliations():
    payload = {
        "articles": [
            {
                "title": "IEEE",
                "article_number": "1234567",
                "authors": {
                    "authors": [{"full_name": "Ada Lovelace", "affiliation": "Research Institute"}]
                },
                "pdf_url": "https://example.test/download",
                "html_url": "https://example.test/full",
                "index_terms": {"author_terms": {"terms": ["Alpha; beta"]}},
            }
        ]
    }
    async with provider_runtime(
        settings=SimpleNamespace(ieee_api_key="test"),
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=payload)),
    ) as runtime:
        record = await runtime.lookup("1234567", provider="ieee")
    assert record.authors[0].affiliations[0].name == "Research Institute"
    assert record.keywords == ("Alpha; beta",)
    assert {link.media_type for link in record.urls if link.kind == "full_text"} == {
        "application/pdf",
        "text/html",
    }


@pytest.mark.parametrize(
    ("names", "affiliations", "expected"),
    [
        (
            ["Doe, Jane", "", "Roe, John"],
            ["First Institute", "Unnamed author's institute", "Second Institute"],
            ["First Institute", "Second Institute"],
        ),
        (["Doe, Jane", "Roe, John"], ["Unmatched Institute"], [None, None]),
    ],
)
async def test_nasa_ads_maps_affiliations_using_original_author_positions(
    names, affiliations, expected
):
    payload = {
        "response": {
            "docs": [
                {
                    "bibcode": "2025ApJ...123..456A",
                    "title": ["Authorship positions"],
                    "author": names,
                    "aff": affiliations,
                }
            ]
        }
    }
    async with provider_runtime(
        settings=SimpleNamespace(nasa_ads_token="test"),
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=payload)),
    ) as runtime:
        record = await runtime.lookup("2025ApJ...123..456A", provider="nasa_ads")
    assert [author.display_name for author in record.authors] == ["Doe, Jane", "Roe, John"]
    assert [
        author.affiliations[0].name if author.affiliations else None for author in record.authors
    ] == expected
