from inquiro.bibliography import (
    builtin_style_catalog,
    builtin_style_xml,
    is_valid_csl,
    render_bibliography,
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
