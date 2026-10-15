from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import httpx2
import pytest
from inquiro import Identifier, SearchClause, SearchQuery
from inquiro.bibliography import export_bibliography_records, work_to_csl_json
from inquiro.canonical import normalize_publication_date
from inquiro.work import read_work, work_doi, work_identifiers
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
    bibliography = {
        "id": "urn:uuid:cf281c3d-c96f-4ce6-a6f1-17460c42e79b",
        "type": "JournalArticle",
        "title": "Publication precision",
        "date_published": normalize_publication_date(publication_date),
    }
    bibliography = {key: value for key, value in bibliography.items() if value is not None}
    assert work_to_csl_json(bibliography).get("issued") == issued


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

    organization, credit = record.work["contributors"]
    assert organization["type"] == "Organization"
    assert organization["organization"]["name"] == "World Health Organization"
    person = credit["person"]
    assert (person["family_name"], person["given_name"]) == ("de la Cruz", "Juan")
    assert person["id"] == "https://orcid.org/0000-0002-1825-0097"
    assert person["affiliations"][0]["identifier"] == "https://ror.org/03yrm5c26"
    assert record.work["subjects"] == [{"subject": "Alpha; beta"}]
    assert record.work["publisher"]["name"] == "Example Publisher"
    assert "container" not in record.work


async def test_openalex_preserves_authorship_affiliation_mapping_and_pdf_metadata():
    payload = {
        "id": "https://openalex.org/W1230000000",
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
        "best_oa_location": {"pdf_url": "https://example.test/download?format=pdf"},
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
        record = await runtime.lookup("W1230000000", provider="openalex")

    ada, _grace, katherine = [credit["person"] for credit in record.work["contributors"]]
    assert (ada["family_name"], ada["given_name"]) == ("Lovelace", "Ada")
    assert ada["affiliations"][0]["identifier"] == "https://ror.org/03yrm5c26"
    assert katherine["affiliations"][0]["name"] == "Research Institute"
    assert record.work["url"] == "https://example.test/article"
    assert record.work["files"][0] == {
        "url": "https://example.test/download?format=pdf",
        "mime_type": "application/pdf",
    }
    assert "CorrespondingAuthor" not in record.work["contributors"][0]["roles"]
    assert record.diagnostics


@pytest.mark.parametrize("operation", ["lookup", "search"])
@pytest.mark.parametrize(
    "raw_name,expected_given",
    [("Xiang Yu", "Xiang"), (None, "Xiang Yang"), ("", "Xiang Yang"), ("   ", "Xiang Yang")],
)
async def test_openalex_uses_the_work_byline_before_the_resolved_author_name(
    operation, raw_name, expected_given
):
    # This name mismatch occurs on DOI 10.1016/j.conengprac.2024.105898.
    payload = {
        "id": "https://openalex.org/W4392452505",
        "doi": "https://doi.org/10.1016/j.conengprac.2024.105898",
        "display_name": "Authorship names",
        "authorships": [
            {
                "raw_author_name": raw_name,
                "author": {
                    "display_name": "Xiang Yang Yu",
                    "orcid": "https://orcid.org/0000-0002-9005-3733",
                },
                "institutions": [
                    {"display_name": "Beihang University", "ror": "https://ror.org/00wk2mp56"}
                ],
            }
        ],
    }
    original = deepcopy(payload)
    response = payload if operation == "lookup" else {"results": [payload], "meta": {"count": 1}}
    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, json=response))
    ) as runtime:
        if operation == "lookup":
            record = await runtime.lookup("10.1016/j.conengprac.2024.105898", provider="openalex")
        else:
            record = (
                await runtime.search(
                    SearchQuery("openalex", (SearchClause("any", "and", "names"),))
                )
            ).results[0]

    (credit,) = record.work["contributors"]
    assert credit["person"] == {
        "given_name": expected_given,
        "family_name": "Yu",
        "id": "https://orcid.org/0000-0002-9005-3733",
        "affiliations": [
            {
                "name": "Beihang University",
                "identifier": "https://ror.org/00wk2mp56",
                "identifier_type": "ROR",
            }
        ],
    }
    assert credit["roles"] == ["Author"]
    assert read_work(payload, "openalex")["contributors"] == [credit]
    assert payload == original


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

    pdf, unknown = record.work["files"]
    assert pdf == {"url": "https://example.test/download", "mime_type": "application/pdf"}
    assert unknown == {"url": "https://example.test/unknown.pdf"}
    assert record.diagnostics


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

    person, organization = record.work["contributors"]
    assert (person["person"]["family_name"], person["person"]["given_name"]) == (
        "de la Cruz",
        "Juan",
    )
    assert person["person"]["affiliations"][0]["identifier"] == "https://ror.org/03yrm5c26"
    assert organization["type"] == "Organization"
    assert record.work["title"] == "Names with <i>structure</i>"
    assert record.work["description"] == "RESULTS: Preserved <sup>2</sup>"
    assert record.work["date_published"] == "2025-10-09"
    assert record.work["subjects"] == [{"subject": "Alpha; beta"}]
    assert ("pmcid", "PMC123") in work_identifiers(record.work)


async def test_pubmed_suffixes_distinguish_authors_in_citation_exports():
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
    <ArticleTitle>Generational names</ArticleTitle><AuthorList>
    <Author><LastName>Smith</LastName><ForeName>John</ForeName><Suffix>Jr</Suffix></Author>
    <Author><LastName>Smith</LastName><ForeName>John</ForeName><Suffix>Sr</Suffix></Author>
    </AuthorList></Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""
    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=xml))
    ) as runtime:
        record = await runtime.lookup("42", provider="pubmed")
    snapshot = deepcopy(record.work)
    authors = work_to_csl_json(record.work)["author"]
    assert authors == [
        {"family": "Smith", "given": "John", "suffix": "Jr"},
        {"family": "Smith", "given": "John", "suffix": "Sr"},
    ]
    assert [credit["person"]["family_name"] for credit in record.work["contributors"]] == [
        "Smith",
        "Smith",
    ]
    for file_format in ("bibtex", "ris"):
        output = export_bibliography_records([record.work], file_format)
        assert "Jr" in output and "Sr" in output
    assert record.work == snapshot


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

    assert work_doi(record.work) == expected
    assert sorted(
        value for namespace, value in work_identifiers(record.work) if namespace == "doi"
    ) == ([expected] if expected else [])
    assert work_to_csl_json(record.work).get("DOI") == expected


async def test_pubmed_preserves_xml_literal_text_and_true_inline_markup():
    xml = """<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>42</PMID><Article>
    <ArticleTitle>List&lt;T&gt; &amp; &lt;i&gt;literal&lt;/i&gt; <i>real &lt;tag&gt;</i> tail &lt;U&gt;</ArticleTitle>
    <Abstract><AbstractText Label="RESULTS &lt;i&gt;literal&lt;/i&gt;">List&lt;T&gt; &amp; &lt;i&gt;literal&lt;/i&gt; <sup>2</sup> tail &lt;U&gt;</AbstractText></Abstract>
    </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>"""

    async with provider_runtime(
        transport=httpx2.MockTransport(lambda _: httpx2.Response(200, text=xml))
    ) as runtime:
        record = await runtime.lookup("42", provider="pubmed")

    assert (
        record.work["title"]
        == "List&lt;T&gt; &amp; &lt;i&gt;literal&lt;/i&gt; <i>real &lt;tag&gt;</i> tail &lt;U&gt;"
    )
    assert (
        record.work["description"]
        == "RESULTS &lt;i&gt;literal&lt;/i&gt;: List&lt;T&gt; &amp; &lt;i&gt;literal&lt;/i&gt; <sup>2</sup> tail &lt;U&gt;"
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

    assert record.work.get("date_published") == expected


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

    assert record.work.get("date_published") == expected
    assert work_to_csl_json(record.work).get("issued") == issued


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
    assert record.work["type"] == ("BookChapter" if is_chapter else "Book")
    assert record.work["title"] == ("Chapter <i>title</i>" if is_chapter else "Book <i>title</i>")
    assert record.work["date_published"] == "2024-02"
    assert record.work["container"].get("title") == ("Book title" if is_chapter else None)
    assert record.work["publisher"]["name"] == "Example Press"
    assert record.work["container"]["volume"] == "2"
    assert record.work["container"].get("first_page") == ("12-18" if is_chapter else None)
    assert record.work["description"] == "SUMMARY: Book <sup>2</sup> summary"
    assert record.work["subjects"] == [{"subject": "Alpha; beta"}]
    assert work_identifiers(record.work) == {("pmid", "43"), ("doi", "10.1000/book-record")}
    assert record.work["url"] == "https://pubmed.ncbi.nlm.nih.gov/43/"
    person = record.work["contributors"][0]["person"]
    assert (person["family_name"], person["given_name"]) == (
        ("de la Cruz", "Juan") if is_chapter else ("Writer", "Ada")
    )
    if is_chapter:
        assert person["id"] == "https://orcid.org/0000-0002-1825-0097"
        assert person["affiliations"][0]["name"] == "Example University"


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

    assert (
        record.work["contributors"][0]["person"]["affiliations"][0]["name"] == "Research Institute"
    )
    assert record.work["subjects"] == [{"subject": "Alpha; beta"}]
    assert {file["mime_type"] for file in record.work["files"]} == {"application/pdf", "text/html"}


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

    people = [credit["person"] for credit in record.work["contributors"]]
    assert [person["name"] for person in people] == ["Doe, Jane", "Roe, John"]
    assert [person.get("affiliations", [{}])[0].get("name") for person in people] == expected
