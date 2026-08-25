import pytest
from inquiro.citations import (
    CitationEngineUnavailable,
    builtin_style_xml,
    is_valid_csl,
    render_bibliography,
)


def test_render_bibliography_reports_unavailable_optional_engine(monkeypatch):
    from inquiro import citations

    monkeypatch.setattr(citations, "CiteProcJSON", None)

    with pytest.raises(CitationEngineUnavailable, match="requires the 'citation' extra"):
        render_bibliography([{"id": "item-1", "title": "Example"}], "<style/>")


def test_is_valid_csl_rejects_garbage():
    assert is_valid_csl("<style/>") is False
    assert is_valid_csl("<style><not-csl/></style>") is False
    apa_xml = builtin_style_xml("apa")
    assert apa_xml is not None
    assert is_valid_csl(apa_xml) is True


def test_builtin_style_xml_unknown_returns_none():
    assert builtin_style_xml("does-not-exist") is None
