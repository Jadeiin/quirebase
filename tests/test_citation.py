from __future__ import annotations

from quirebase.citation import (
    BUILTIN_STYLES,
    available_builtin_styles,
    builtin_style_xml,
    is_valid_csl,
    item_to_csl_json,
    render_citation,
)
from quirebase.models import Item, User

_counter = 0


def _item(db, **overrides) -> Item:
    global _counter
    _counter += 1
    user = User(username=f"citation-{_counter}", password_hash="unused")
    db.add(user)
    db.flush()
    fields = {
        "title": "An Example Paper",
        "authors": "Doe, Jane; Smith, Alex",
        "editors": "Editor, Ada",
        "publication_title": "Testing Quarterly",
        "publication_date": "2025-02-03",
        "doi": "10.1234/example",
        "keywords": "search; testing",
        "abstract": "A full abstract.",
        "reference_type": "journal-article",
    }
    fields.update(overrides)
    item = Item(created_by=user.id, **fields)
    db.add(item)
    db.flush()
    return item


def test_item_to_csl_json_maps_core_fields(db):
    record = item_to_csl_json(_item(db))

    assert record["type"] == "article-journal"
    assert record["title"] == "An Example Paper"
    assert record["DOI"] == "10.1234/example"
    assert record["container-title"] == "Testing Quarterly"
    assert record["issued"]["date-parts"] == [[2025, 2, 3]]
    assert [name["family"] for name in record["author"]] == ["Doe", "Smith"]
    assert record["author"][0]["given"] == "Jane"
    assert record["editor"][0]["family"] == "Editor"
    assert record["keyword"] == ["search", "testing"]


def test_item_to_csl_json_maps_reference_types(db):
    assert item_to_csl_json(_item(db, reference_type="book"))["type"] == "book"
    assert item_to_csl_json(_item(db, reference_type="preprint"))["type"] == "article"
    assert item_to_csl_json(_item(db, reference_type="thesis"))["type"] == "thesis"
    assert item_to_csl_json(_item(db, reference_type="unknown-type"))["type"] == "article"


def test_author_names_without_commas_use_last_token_as_family(db):
    record = item_to_csl_json(_item(db, authors="Ada Lovelace"))
    assert record["author"] == [{"family": "Lovelace", "given": "Ada"}]


def test_builtin_styles_render(db):
    item = _item(db)
    for style_key in BUILTIN_STYLES:
        xml = builtin_style_xml(style_key)
        assert xml is not None, style_key
        rendered = render_citation(item, xml)
        assert "An Example Paper" in rendered


def test_render_citation_html(db):
    item = _item(db)
    rendered = render_citation(item, builtin_style_xml("apa"), output_format="html")
    assert "An Example Paper" in rendered


def test_is_valid_csl_rejects_garbage():
    assert is_valid_csl("<style/>") is False
    assert is_valid_csl("<style><not-csl/></style>") is False
    assert is_valid_csl(builtin_style_xml("apa")) is True


def test_builtin_style_xml_unknown_returns_none():
    assert builtin_style_xml("does-not-exist") is None


def test_available_builtin_styles_lists_installed_styles():
    available = available_builtin_styles()
    assert set(available) == set(BUILTIN_STYLES)


def test_builtin_style_xml_degrades_when_styles_package_is_missing(monkeypatch):
    monkeypatch.setattr("quirebase.citation.get_style_filepath", None)
    available_builtin_styles.cache_clear()
    try:
        assert builtin_style_xml("apa") is None
        assert available_builtin_styles() == {}
    finally:
        available_builtin_styles.cache_clear()
