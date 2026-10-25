from copy import deepcopy

import pytest
from inquiro.bibliography import (
    builtin_style_catalog,
    builtin_style_xml,
    is_valid_csl,
    render_bibliography,
    render_citation,
    styles,
)


def test_render_bibliography_with_custom_csl_without_optional_style_catalog(monkeypatch):
    monkeypatch.setattr(styles, "get_style_filepath", None)
    monkeypatch.setattr(styles, "get_style_name", None)
    builtin_style_catalog.cache_clear()
    xml = """<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0" class="in-text">
    <info><title>Custom</title><id>https://example.test/custom</id>
    <updated>2026-10-10T00:00:00+00:00</updated></info>
    <citation><layout><text variable="title"/></layout></citation></style>"""
    try:
        assert builtin_style_catalog() == ()
        assert builtin_style_xml("apa") is None
        assert is_valid_csl(xml)
        assert render_bibliography([{"id": "item-1", "type": "book", "title": "Example"}], xml) == [
            "Example"
        ]
    finally:
        builtin_style_catalog.cache_clear()


def test_is_valid_csl_rejects_garbage():
    assert is_valid_csl("<style/>") is False
    assert is_valid_csl("<style><not-csl/></style>") is False
    apa_xml = builtin_style_xml("apa")
    assert apa_xml is not None
    assert is_valid_csl(apa_xml) is True


def test_builtin_style_xml_unknown_returns_none():
    assert builtin_style_xml("does-not-exist") is None


def _apa_work(*authors: tuple[str, str]) -> dict:
    return {
        "id": "https://doi.org/10.1234/example",
        "type": "JournalArticle",
        "title": "Example",
        "contributors": [
            {
                "type": "Person",
                "person": {"given_name": given, "family_name": family},
                "roles": ["Author"],
            }
            for given, family in authors
        ],
        "date_published": "2024-01-01",
        "container": {
            "type": "Journal",
            "title": "Journal of Examples",
            "volume": "1",
            "issue": "2",
            "first_page": "1",
            "last_page": "2",
        },
    }


@pytest.mark.parametrize("output_format", ["text", "html"])
def test_apa_does_not_duplicate_period_after_initial(output_format):
    xml = builtin_style_xml("apa")
    assert xml is not None
    rendered = render_citation(
        _apa_work(("Ada", "Lovelace"), ("Grace", "Hopper")),
        xml,
        output_format=output_format,
    )
    assert "Hopper, G.. (" not in rendered
    assert "Hopper, G. (2024)" in rendered


@pytest.mark.parametrize("output_format", ["text", "html"])
def test_apa_single_author_does_not_duplicate_period(output_format):
    xml = builtin_style_xml("apa")
    assert xml is not None
    rendered = render_citation(_apa_work(("Ada", "Lovelace")), xml, output_format=output_format)
    assert "Lovelace, A.. (" not in rendered
    assert "Lovelace, A. (2024)" in rendered


@pytest.mark.parametrize(
    "field", ["title", "container-title", "publisher", "abstract", "author", "editor"]
)
def test_direct_csl_rendering_sanitizes_nested_display_values(field):
    malicious = (
        'Visible<script>alert(1)</script><i onclick="alert(2)">Safe</i><img src=x onerror=alert(3)>'
    )
    entry = {"id": "citation-1", "type": "book"}
    if field in {"author", "editor"}:
        entry[field] = [{"family": malicious, "given": "Jane"}]
        layout = f'<names variable="{field}"><name/></names>'
    else:
        entry[field] = malicious
        layout = f'<text variable="{field}"/>'
    before = deepcopy(entry)
    xml = f"""<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0" class="in-text">
    <info><title>Safety</title><id>https://example.test/safety</id>
    <updated>2026-10-10T00:00:00+00:00</updated></info>
    <citation><layout>{layout}</layout></citation></style>"""
    output = render_bibliography([entry], xml, output_format="html")[0]
    assert "visible" in output.lower() and "safe" in output.lower()
    assert "<script" not in output and "alert(" not in output
    assert "onclick" not in output and "onerror" not in output and "<img" not in output
    assert entry == before
