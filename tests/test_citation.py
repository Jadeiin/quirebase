from __future__ import annotations

import pytest
from inquiro.bibliography import (
    BibliographyExportOptions,
    CitationEngineUnavailable,
    builtin_style_xml,
    record_from_item,
    record_to_csl_json,
    render_citation,
)

from quirebase.core.errors import ValidationFailure
from quirebase.library.citations import (
    create_custom_citation_style,
    format_csl_export,
    format_standard_export,
    get_item_citation_text_response,
    preview_citation_key,
    resolve_style_xml,
    select_builtin_citation_styles,
)
from quirebase.models import CitationStyle, Item, User

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
    record = record_to_csl_json(record_from_item(_item(db)))

    assert record["type"] == "article-journal"
    assert record["title"] == "An Example Paper"
    assert record["DOI"] == "10.1234/example"
    assert record["container-title"] == "Testing Quarterly"
    assert record["issued"]["date-parts"] == [[2025, 2, 3]]
    assert [name["family"] for name in record["author"]] == ["Doe", "Smith"]
    assert record["author"][0]["given"] == "Jane"
    assert record["editor"][0]["family"] == "Editor"
    assert record["keyword"] == ["search", "testing"]


def test_item_to_csl_json_projects_canonical_rich_text_to_plaintext(db):
    record = record_to_csl_json(
        record_from_item(
            _item(
                db,
                title="Using <i>AI</i> &amp; ML",
                abstract="A <b>formatted</b> result with H<sub>2</sub>O.",
            )
        )
    )

    assert record["title"] == "Using AI & ML"
    assert record["abstract"] == "A formatted result with H2O."


def test_export_options_control_abstract_and_journal_abbreviation(db):
    item = _item(db, journal_abbreviation="TQ")
    options = BibliographyExportOptions(include_abstract=False, journal_mode="prefer_abbreviated")
    record = record_to_csl_json(record_from_item(item), options)

    assert "abstract" not in record
    assert record["container-title"] == "TQ"


def test_citation_key_preview_shows_key_and_disambiguation_suffix():
    assert (
        preview_citation_key("auth.capitalize + year + shorttitle(1).capitalize", force_ascii=True)
        == "LovelaceXXXXSketch  LovelaceXXXXSketcha"
    )
    assert preview_citation_key("auth.lower + year") == "lovelaceXXXX  lovelaceXXXXa"


def test_citation_key_preview_rejects_invalid_formulas():
    with pytest.raises(ValidationFailure):
        preview_citation_key("auth + unknown")

    with pytest.raises(ValidationFailure):
        preview_citation_key("x" * 1001)


def test_standard_export_applies_citation_key_formula_to_keyless_items(db):
    item = _item(db, title="An Example Paper")
    item.bibtex_id = None

    contents, _media_type, _filename = format_standard_export(
        [item],
        "bibtex",
        options=BibliographyExportOptions(
            citation_key_formula="auth.lower + year",
            citation_key_force_ascii=True,
        ),
    )

    assert "@article{doe2025," in contents


def test_standard_export_rejects_invalid_citation_key_formula(db):
    with pytest.raises(ValidationFailure):
        format_standard_export(
            [_item(db)],
            "bibtex",
            options=BibliographyExportOptions(citation_key_formula="auth + unknown"),
        )


def test_builtin_style_catalog_is_searchable(db):
    selection = select_builtin_citation_styles("american medical", limit=10)

    assert selection.included is None
    assert selection.matches
    assert any("medical" in style.name.lower() for style in selection.matches)


def test_builtin_style_selection_reuses_one_catalog_snapshot(monkeypatch):
    from inquiro.bibliography import styles

    from quirebase.library import citations

    catalog_calls = 0
    catalog = (
        citations.CitationStyleOption(key="matching", name="Matching Style"),
        citations.CitationStyleOption(key="saved", name="Saved Style"),
    )

    def load_catalog():
        nonlocal catalog_calls
        catalog_calls += 1
        return catalog

    styles.builtin_style_catalog.cache_clear()
    monkeypatch.setattr(styles, "builtin_style_catalog", load_catalog)

    selection = citations.select_builtin_citation_styles("matching", limit=1, include="saved")

    assert catalog_calls == 1
    assert selection.matches == (catalog[0],)
    assert selection.included == catalog[1]


def test_citation_copy_endpoint_accepts_export_options(db, tmp_path, monkeypatch):
    from test_http import authenticated_client

    from quirebase.core.config import get_settings
    from quirebase.web.app import app

    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        response = client.get(
            f"/documents/{item.id}/citation-copy",
            params={
                "file_format": "bibtex",
                "include_abstract": "false",
                "preserve_case": "true",
                "journal_mode": "prefer_abbreviated",
            },
        )
        assert response.status_code == 200
        assert "abstract" not in response.text
        assert "title = {{P}aper}" in response.text
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_citation_style_search_includes_owned_custom_styles(db, tmp_path, monkeypatch):
    from test_http import authenticated_client

    from quirebase.core.config import get_settings
    from quirebase.web.app import app

    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        user = db.get(User, item.created_by)
        xml = builtin_style_xml("apa")
        assert user is not None and xml is not None
        create_custom_citation_style(db, user, "My Searchable Style", xml)
        response = client.get("/api/citation-styles?query=searchable")
        assert response.status_code == 200
        assert response.json()["styles"][0]["name"] == "My Searchable Style"
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_citation_style_search_includes_requested_saved_style(db, tmp_path, monkeypatch):
    from test_http import authenticated_client

    from quirebase.core.config import get_settings
    from quirebase.web.app import app

    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        response = client.get("/api/citation-styles", params={"limit": 1, "include": "apa"})
        assert response.status_code == 200
        styles = response.json()["styles"]
        assert len(styles) == 2
        assert styles[-1] == {
            "key": "apa",
            "name": "APA Style 7th edition",
            "scope": "builtin",
        }
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_item_to_csl_json_maps_reference_types(db):
    assert record_to_csl_json(record_from_item(_item(db, reference_type="book")))["type"] == "book"
    assert (
        record_to_csl_json(record_from_item(_item(db, reference_type="preprint")))["type"]
        == "article"
    )
    assert (
        record_to_csl_json(record_from_item(_item(db, reference_type="thesis")))["type"] == "thesis"
    )
    assert (
        record_to_csl_json(record_from_item(_item(db, reference_type="unknown-type")))["type"]
        == "article"
    )


def test_author_names_without_commas_use_last_token_as_family(db):
    record = record_to_csl_json(record_from_item(_item(db, authors="Ada Lovelace")))
    assert record["author"] == [{"family": "Lovelace", "given": "Ada"}]


def test_builtin_styles_render(db):
    item = _item(db)
    for style_key in ("apa", "ieee", "modern-language-association"):
        xml = builtin_style_xml(style_key)
        assert xml is not None, style_key
        rendered = render_citation(record_from_item(item), xml)
        assert "An Example Paper" in rendered


def test_render_citation_html(db):
    item = _item(db)
    apa_xml = builtin_style_xml("apa")
    assert apa_xml is not None
    rendered = render_citation(record_from_item(item), apa_xml, output_format="html")
    assert "An Example Paper" in rendered


def test_resolve_style_xml_scoped_to_owner(db):
    csl_xml = builtin_style_xml("apa")
    assert csl_xml is not None
    user_a = User(username="owner-a", password_hash="unused")
    user_b = User(username="owner-b", password_hash="unused")
    db.add_all([user_a, user_b])
    db.flush()

    style_a = create_custom_citation_style(db, user_a, "Custom A", csl_xml)

    # Owner can resolve
    assert resolve_style_xml(db, user_a, style_a.id) == csl_xml
    # Non-owner cannot resolve
    assert resolve_style_xml(db, user_b, style_a.id) is None
    # Unauthenticated cannot resolve
    assert resolve_style_xml(db, None, style_a.id) is None
    # Built-in styles remain resolvable by anyone
    assert resolve_style_xml(db, user_a, "apa") == csl_xml
    assert resolve_style_xml(db, user_b, "apa") == csl_xml
    assert resolve_style_xml(db, None, "apa") == csl_xml


def test_csl_export_translates_unavailable_engine_at_library_interface(db, monkeypatch):
    from quirebase.library import citations

    item = _item(db)
    user = db.get(User, item.created_by)
    assert user is not None
    style = CitationStyle(name="Persisted Style", csl_xml="<style/>", created_by=user.id)
    db.add(style)
    db.flush()

    def unavailable(*_args, **_kwargs):
        raise CitationEngineUnavailable("CSL formatting requires the 'citation' extra")

    monkeypatch.setattr(citations, "render_bibliography", unavailable)

    with pytest.raises(ValidationFailure, match="requires the 'citation' extra"):
        format_csl_export(db, user, [item], style_key=style.id)


def test_citation_text_translates_unavailable_engine_at_library_interface(db, monkeypatch):
    from quirebase.library import citations

    item = _item(db)
    user = db.get(User, item.created_by)
    assert user is not None
    style = CitationStyle(name="Persisted Style", csl_xml="<style/>", created_by=user.id)
    db.add(style)
    db.flush()

    def unavailable(*_args, **_kwargs):
        raise CitationEngineUnavailable("CSL formatting requires the 'citation' extra")

    monkeypatch.setattr(citations, "render_citation", unavailable)

    with pytest.raises(ValidationFailure, match="requires the 'citation' extra"):
        get_item_citation_text_response(db, user, item.id, style_key=style.id)


def test_citation_routes_enforce_custom_style_ownership(db, tmp_path, monkeypatch):
    from test_http import authenticated_client

    from quirebase.core.config import get_settings
    from quirebase.web.app import app

    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        user_a = db.get(User, item.created_by)
        assert user_a is not None
        user_b = User(username="other-user", password_hash="unused")
        db.add(user_b)
        db.flush()

        csl_xml = builtin_style_xml("apa")
        assert csl_xml is not None
        style_a = create_custom_citation_style(db, user_a, "User A Style", csl_xml)
        style_b = create_custom_citation_style(db, user_b, "User B Style", csl_xml)

        # User A requesting User A's style succeeds
        res = client.get(f"/documents/{item.id}/citation-text?style={style_a.id}")
        assert res.status_code == 200
        assert item.title in res.text

        # User A requesting User B's style is forbidden / invalid
        res_forbidden = client.get(f"/documents/{item.id}/citation-text?style={style_b.id}")
        assert res_forbidden.status_code == 422

        res_csl_forbidden = client.get(
            f"/documents/{item.id}/citation?file_format=csl&style={style_b.id}"
        )
        assert res_csl_forbidden.status_code == 422
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_custom_styles_accessible_in_item_workspace(db, tmp_path, monkeypatch):
    from test_http import authenticated_client

    from quirebase.core.config import get_settings
    from quirebase.web.app import app

    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        user = db.get(User, item.created_by)
        csl_xml = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0" class="in-text">\n'
            "  <info><id>test</id><title>Test Custom</title><updated>2025-01-01T00:00:00Z</updated></info>\n"
            '  <citation><layout><text variable="title"/></layout></citation>\n'
            '  <bibliography><layout><text variable="title"/></layout></bibliography>\n'
            "</style>"
        )
        custom_style = create_custom_citation_style(db, user, "My Isolated Custom Style", csl_xml)

        response = client.get(f"/items/{item.id}")
        assert response.status_code == 200
        assert 'x-data="formattedCitation"' not in response.text
        assert 'x-data="itemExport"' in response.text

        text_res = client.get(f"/documents/{item.id}/citation-text?style={custom_style.id}")
        assert text_res.status_code == 200
        assert item.title in text_res.text
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
