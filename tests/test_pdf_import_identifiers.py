from __future__ import annotations

import pymupdf
import pytest
from inquiro import Identifier

from quirebase.library.identifiers import extract_pdf_lookup_identifier


@pytest.mark.parametrize("page_index", [0, 1, 7])
def test_reference_doi_is_not_the_uploaded_pdfs_identity(tmp_path, page_index):
    # RSS22 p175 has no document-level identifier; its first DOI is a reference on page 8.
    source = tmp_path / "references.pdf"
    with pymupdf.open() as document:
        for _ in range(page_index + 1):
            document.new_page()
        document[page_index].insert_text(
            (72, 200), "References\n[1] Another paper. DOI:10.1109/MCSE.2007.55"
        )
        document.save(source)

    assert extract_pdf_lookup_identifier(source) is None


@pytest.mark.parametrize("field", ["title", "subject"])
@pytest.mark.parametrize(
    "value,expected",
    [
        ("10.1234/Article", "10.1234/article"),
        ("doi: 10.1234/Article", "10.1234/article"),
        ("urn:doi:10.1234/Article", "10.1234/article"),
        ("https://doi.org/10.1234/Article", "10.1234/article"),
        ("https://dx.doi.org/10.1234/A%28B%29", "10.1234/a(b)"),
    ],
)
def test_pdf_info_requires_an_entire_doi_value(tmp_path, field, value, expected):
    source = tmp_path / "article.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 72), "Reference DOI:10.1234/citation")
        document.set_metadata({field: value})
        document.save(source)

    assert extract_pdf_lookup_identifier(source) == Identifier("doi", expected)


@pytest.mark.parametrize(
    "metadata",
    [
        {"title": "Related work DOI:10.1234/citation"},
        {"subject": "doi:10.1234/one; doi:10.1234/two"},
        {"keywords": "doi:10.1234/citation"},
        {"keywords": "arXiv:2304.08030v2"},
        {"subject": "https://arxiv.org/abs/2304.08030v2"},
        {"title": "doi:10.1234/one", "subject": "doi:10.1234/two"},
    ],
)
def test_unrelated_or_conflicting_info_does_not_identify_a_pdf(tmp_path, metadata):
    source = tmp_path / "article.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.set_metadata(metadata)
        document.save(source)

    assert extract_pdf_lookup_identifier(source) is None


def xmp_packet(properties="", attributes=""):
    return f"""<x:xmpmeta xmlns:x="adobe:ns:meta/">
        <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
        <rdf:Description rdf:about=""
            xmlns:prism="http://prismstandard.org/namespaces/basic/2.0/"
            xmlns:pdfx="http://ns.adobe.com/pdfx/1.3/"
            xmlns:dc="http://purl.org/dc/elements/1.1/"
            {attributes}>{properties}</rdf:Description></rdf:RDF></x:xmpmeta>"""


@pytest.mark.parametrize(
    "properties,attributes",
    [
        ("<prism:doi>10.1234/Article</prism:doi>", ""),
        ("", 'prism:doi="10.1234/Article"'),
        ("<pdfx:DOI>10.1234/Article</pdfx:DOI>", ""),
        ("<pdfx:doi>10.1234/Article</pdfx:doi>", ""),
        ("<dc:identifier>doi:10.1234/Article</dc:identifier>", ""),
        (
            (
                "<dc:identifier><rdf:Bag><rdf:li>https://doi.org/10.1234/Article</rdf:li>"
                "</rdf:Bag></dc:identifier>"
            ),
            "",
        ),
    ],
)
def test_xmp_doi_fields_precede_lower_confidence_metadata(tmp_path, properties, attributes):
    source = tmp_path / "article.pdf"
    with pymupdf.open() as document:
        document.new_page().insert_text((72, 200), "References DOI:10.1234/citation")
        document.set_metadata({"subject": "doi:10.1234/info"})
        document.set_xml_metadata(xmp_packet(properties, attributes))
        document.save(source)

    assert extract_pdf_lookup_identifier(source) == Identifier("doi", "10.1234/article")


@pytest.mark.parametrize(
    "xml",
    [
        "<malformed",
        xmp_packet("<dc:description>DOI:10.1234/citation</dc:description>"),
        xmp_packet("<dc:identifier>References DOI:10.1234/citation</dc:identifier>"),
    ],
)
def test_unrelated_or_malformed_xmp_does_not_identify_a_pdf(tmp_path, xml):
    source = tmp_path / "article.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.set_xml_metadata(xml)
        document.save(source)

    assert extract_pdf_lookup_identifier(source) is None


def test_conflicting_xmp_identifiers_do_not_fall_back_to_weaker_metadata(tmp_path):
    source = tmp_path / "ambiguous.pdf"
    with pymupdf.open() as document:
        document.new_page()
        document.set_metadata({"subject": "10.1234/info"})
        document.set_xml_metadata(
            xmp_packet("<prism:doi>10.1234/one</prism:doi><pdfx:doi>10.1234/two</pdfx:doi>")
        )
        document.save(source)

    assert extract_pdf_lookup_identifier(source) is None


@pytest.mark.parametrize(
    "uri,expected",
    [
        (
            "https://crossmark.crossref.org/dialog/?doi=10.1234%2FArticle&domain=pdf",
            "10.1234/article",
        ),
        (
            "https://publisher.example/action/showCitFormats?doi=10.1234%2FArticle",
            "10.1234/article",
        ),
        ("https://www.mdpi.com/article/10.3390/example?type=check_update", "10.3390/example"),
        ("https://doi.org/10.1234/citation", None),
        ("https://publisher.example/lookup/doi/10.1234/citation", None),
        ("https://crossmark.crossref.org.evil.example/dialog/?doi=10.1234/citation", None),
        ("https://www.mdpi.com/article/10.3390/example", None),
        ("https://crossmark.crossref.org/dialog/?doi=10.1234/one&doi=10.1234/two", None),
    ],
)
def test_only_first_page_publisher_identity_links_are_lookup_evidence(tmp_path, uri, expected):
    source = tmp_path / "article.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_link({
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(30, 30, 60, 60),
            "uri": uri,
        })
        document.save(source)

    found = extract_pdf_lookup_identifier(source)
    assert found == (Identifier("doi", expected) if expected else None)


def test_later_publisher_links_do_not_identify_a_pdf(tmp_path):
    source = tmp_path / "article.pdf"
    with pymupdf.open() as document:
        document.new_page()
        page = document.new_page()
        page.insert_link({
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(30, 30, 60, 60),
            "uri": "https://crossmark.crossref.org/dialog/?doi=10.1234/citation",
        })
        document.save(source)

    assert extract_pdf_lookup_identifier(source) is None


@pytest.mark.parametrize(
    "other,expected",
    [("10.1234/Article", Identifier("doi", "10.1234/article")), ("10.1234/different", None)],
)
def test_publisher_link_conflicts_are_not_resolved_by_info_metadata(tmp_path, other, expected):
    source = tmp_path / "article.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        for index, doi in enumerate(("10.1234/article", other)):
            page.insert_link({
                "kind": pymupdf.LINK_URI,
                "from": pymupdf.Rect(30 + index * 40, 30, 60 + index * 40, 60),
                "uri": f"https://crossmark.crossref.org/dialog/?doi={doi}",
            })
        document.set_metadata({"subject": "10.1234/info"})
        document.save(source)

    assert extract_pdf_lookup_identifier(source) == expected


@pytest.mark.parametrize(
    "identifier", ["2304.08030v2", "0704.0001v1", "hep-th/9901001v2", "math.GT/0309136"]
)
@pytest.mark.parametrize("rotation", [0, 90])
def test_first_page_rotated_left_arxiv_watermarks_identify_preprints(
    tmp_path, identifier, rotation
):
    source = tmp_path / "arxiv.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((30, 700), f"arXiv:{identifier} [cs.CL] 18 Apr 2023", rotate=90)
        page.set_rotation(rotation)
        document.save(source)

    assert extract_pdf_lookup_identifier(source) == Identifier("arxiv", identifier)


@pytest.mark.parametrize(
    "position,rotation,page_index,text",
    [
        ((72, 72), 0, 0, "arXiv:2304.08030v2 [cs.CL]"),
        ((72, 72), 0, 0, "https://arxiv.org/pdf/2304.08030v2.pdf"),
        ((100, 700), 90, 0, "arXiv:2304.08030v2 [cs.CL]"),
        ((560, 700), 90, 0, "arXiv:2304.08030v2 [cs.CL]"),
        ((30, 700), 90, 1, "arXiv:2304.08030v2 [cs.CL]"),
        ((30, 300), 270, 0, "arXiv:2304.08030v2 [cs.CL]"),
        ((30, 700), 90, 0, "arXiv:2304.080300"),
        ((30, 700), 90, 0, "arXiv:2304.08030invalid"),
    ],
)
def test_arxiv_citations_and_invalid_watermarks_do_not_identify_a_pdf(
    tmp_path, position, rotation, page_index, text
):
    source = tmp_path / "article.pdf"
    with pymupdf.open() as document:
        for _ in range(page_index + 1):
            document.new_page()
        document[page_index].insert_text(position, text, rotate=rotation)
        document.save(source)

    assert extract_pdf_lookup_identifier(source) is None


def test_rotated_arxiv_watermark_is_preferred_to_reference_doi(tmp_path):
    source = tmp_path / "arxiv.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), "A reference: doi:10.1234/citation")
        page.insert_text((30, 700), "arXiv:2304.08030v2 [cs.CL] 18 Apr 2023", rotate=90)
        document.set_metadata({"subject": "10.1234/published-version"})
        document.save(source)

    assert extract_pdf_lookup_identifier(source) == Identifier("arxiv", "2304.08030v2")


def test_conflicting_arxiv_watermarks_do_not_fall_back_to_doi(tmp_path):
    source = tmp_path / "ambiguous.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_text((30, 700), "arXiv:2304.08030v2 [cs.CL]", rotate=90)
        page.insert_text((30, 400), "arXiv:0704.0001v1 [math.CO]", rotate=90)
        document.set_metadata({"subject": "10.1234/info"})
        document.save(source)

    assert extract_pdf_lookup_identifier(source) is None
