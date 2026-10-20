from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app_helpers import json_payload
from inquiro.bibliography import (
    BibliographyExportOptions,
    builtin_style_xml,
    render_citation,
    work_to_csl_json,
)
from item_helpers import contributor_values
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.errors import (
    PermissionDenied,
    ResourceUnavailable,
    ValidationFailure,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
)
from quirebase.library.citations import (
    BibliographyFormat,
    create_custom_citation_style,
    delete_custom_citation_style,
    export_item_bibliography,
    export_selected_bibliography,
    list_custom_citation_styles,
    preview_citation_key,
    render_item_citation,
    resolve_style_xml,
    select_builtin_citation_styles,
)
from quirebase.models import CitationStyle, Item, User, WorkspaceMember, WorkspaceRole
from quirebase.workspaces import archive_workspace

_counter = 0


async def _async_item(db, **overrides) -> Item:
    global _counter
    _counter += 1
    user = User(username=f"citation-async-{_counter}", password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    work = {
        "id": "https://doi.org/10.1234/example",
        "type": "JournalArticle",
        "title": "An Example Paper",
        "contributors": contributor_values("Doe, Jane; Smith, Alex"),
        "container": {"title": "Testing Quarterly"},
        "date_published": "2025-02-03",
        "description": "A full abstract.",
        "subjects": [{"subject": "search"}, {"subject": "testing"}],
    }
    editor = contributor_values("Editor, Ada")[0]
    editor["roles"] = ["Editor"]
    work["contributors"].append(editor)
    for key, value in overrides.items():
        if key == "reference_type":
            work["type"] = {
                "book": "Book",
                "preprint": "Preprint",
                "thesis": "Dissertation",
                "document": "Document",
            }[value]
        elif key == "authors":
            work["contributors"] = contributor_values(value)
        elif key == "editors":
            credits = contributor_values(value)
            for credit in credits:
                credit["roles"] = ["Editor"]
            work["contributors"] += credits
        else:
            work[
                {"abstract": "description", "publication_date": "date_published"}.get(key, key)
            ] = value
    item = Item(workspace_id=fixture_workspace_id(user), created_by=user.id, work=work)
    db.add(item)
    await db.flush()
    return item


@pytest.mark.anyio
@pytest.mark.parametrize("role", [WorkspaceRole.viewer, WorkspaceRole.reviewer])
async def test_shared_citation_style_writes_require_resource_action(async_db, role):
    item = await _async_item(async_db)
    owner = await async_db.get(User, item.created_by)
    assert owner is not None
    contributor = User(username=f"style-{role.value}-writer", password_hash="unused")
    async_db.add(contributor)
    await async_db.flush()
    await provision_initial_workspace(async_db, contributor)
    async_db.add(WorkspaceMember(workspace_id=item.workspace_id, user_id=contributor.id, role=role))
    await async_db.commit()
    xml = builtin_style_xml("apa")
    assert xml is not None
    style = await create_custom_citation_style(async_db, owner, item.workspace_id, "Shared", xml)
    with pytest.raises(PermissionDenied):
        await create_custom_citation_style(async_db, contributor, item.workspace_id, "Other", xml)
    with pytest.raises(PermissionDenied):
        await delete_custom_citation_style(async_db, contributor, item.workspace_id, style.id)
    assert await async_db.get(CitationStyle, style.id) is not None


@pytest.mark.anyio
async def test_shared_citation_style_duplicate_and_archived_workspace(async_db):
    item = await _async_item(async_db)
    owner = await async_db.get(User, item.created_by)
    assert owner is not None
    xml = builtin_style_xml("apa")
    assert xml is not None
    style = await create_custom_citation_style(async_db, owner, item.workspace_id, "Shared", xml)
    with pytest.raises(ValidationFailure, match="already exists"):
        await create_custom_citation_style(async_db, owner, item.workspace_id, " Shared ", xml)
    await archive_workspace(async_db, owner, item.workspace_id)
    with pytest.raises(WorkspaceLifecycleError):
        await create_custom_citation_style(async_db, owner, item.workspace_id, "Other", xml)
    with pytest.raises(WorkspaceLifecycleError):
        await delete_custom_citation_style(async_db, owner, item.workspace_id, style.id)


@pytest.mark.anyio
async def test_shared_citation_styles_require_workspace_membership_to_list(async_db):
    item = await _async_item(async_db)
    outsider = User(username="style-outsider", password_hash="unused")
    async_db.add(outsider)
    await async_db.flush()
    await provision_initial_workspace(async_db, outsider)
    await async_db.commit()
    with pytest.raises(WorkspaceMembershipRequired):
        await list_custom_citation_styles(async_db, outsider, item.workspace_id)


@pytest.mark.anyio
async def test_duplicate_shared_citation_style_returns_validation_response(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    from test_http import authenticated_async_client

    from quirebase.core.config import get_settings

    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        xml = builtin_style_xml("apa")
        assert xml is not None
        url = f"/api/v1/workspaces/{item.workspace_id}/citation-styles"
        payload = {"name": "Shared", "csl": xml}
        assert (await client.post(url, json=json_payload(payload))).status_code == 201
        duplicate = await client.post(url, json=json_payload(payload))
        assert duplicate.status_code == 422
        assert duplicate.json()["code"] == "validation_failed"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_to_csl_json_maps_core_fields(async_db):
    record = work_to_csl_json((await _async_item(async_db)).work)
    assert record["type"] == "article-journal"
    assert record["title"] == "An Example Paper"
    assert record["DOI"] == "10.1234/example"
    assert record["container-title"] == "Testing Quarterly"
    assert record["issued"]["date-parts"] == [[2025, 2, 3]]
    assert [name["family"] for name in record["author"]] == ["Doe", "Smith"]
    assert record["author"][0]["given"] == "Jane"
    assert record["editor"][0]["family"] == "Editor"
    assert record["categories"] == ["search", "testing"]


@pytest.mark.anyio
async def test_item_to_csl_json_preserves_supported_rich_text(async_db):
    record = work_to_csl_json(
        (
            await _async_item(
                async_db,
                title="Using <i>AI</i> &amp; ML",
                abstract="A <b>formatted</b> result with H<sub>2</sub>O.",
            )
        ).work
    )
    assert record["title"] == "Using <i>AI</i> &amp; ML"
    assert record["abstract"] == "A <b>formatted</b> result with H<sub>2</sub>O."


@pytest.mark.anyio
async def test_export_options_control_abstract(async_db):
    item = await _async_item(async_db)
    options = BibliographyExportOptions(include_abstract=False)
    record = work_to_csl_json(item.work, options)
    assert "abstract" not in record
    assert record["container-title"] == "Testing Quarterly"


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


@pytest.mark.anyio
async def test_standard_export_applies_citation_key_formula_to_keyless_items(async_db):
    item = await _async_item(async_db, title="An Example Paper")
    item.citation_key = None
    item.work = {
        **item.work,
        "contributors": [
            credit for credit in item.work["contributors"] if "Author" in credit["roles"]
        ],
    }
    user = await async_db.get(User, item.created_by)
    assert user is not None
    export = await export_item_bibliography(
        async_db,
        user,
        item.workspace_id,
        item.id,
        BibliographyFormat.bibtex,
        options=BibliographyExportOptions(
            citation_key_formula="auth.lower + year", citation_key_force_ascii=True
        ),
    )
    assert "@article{doe2025," in export.content


@pytest.mark.anyio
async def test_standard_export_rejects_invalid_citation_key_formula(async_db):
    item = await _async_item(async_db)
    user = await async_db.get(User, item.created_by)
    assert user is not None
    with pytest.raises(ValidationFailure):
        await export_item_bibliography(
            async_db,
            user,
            item.workspace_id,
            item.id,
            BibliographyFormat.bibtex,
            options=BibliographyExportOptions(citation_key_formula="auth + unknown"),
        )


@pytest.mark.anyio
async def test_selected_bibliography_preserves_requested_order_and_deduplicates(async_db):
    first = await _async_item(async_db)
    second = Item(
        workspace_id=first.workspace_id,
        created_by=first.created_by,
        work={**first.work, "title": "Second result"},
    )
    async_db.add(second)
    await async_db.flush()
    user = await async_db.get(User, first.created_by)
    assert user is not None
    export = await export_selected_bibliography(
        async_db,
        user,
        first.workspace_id,
        [second.id, first.id, second.id],
        BibliographyFormat.csl_json,
    )
    assert [entry["title"] for entry in json.loads(export.content)] == [
        "Second result",
        "An Example Paper",
    ]


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["item", "selection"])
@pytest.mark.parametrize("target", ["missing", "other_workspace"])
async def test_bibliography_rejects_missing_and_other_workspace_items(async_db, scope, target):
    item = await _async_item(async_db)
    user = await async_db.get(User, item.created_by)
    assert user is not None
    target_id = (await _async_item(async_db)).id if target == "other_workspace" else uuid4()
    if scope == "item":
        with pytest.raises(ResourceUnavailable, match="Item not found"):
            await export_item_bibliography(
                async_db, user, item.workspace_id, target_id, BibliographyFormat.bibtex
            )
    else:
        with pytest.raises(ValidationFailure, match="accessible Items"):
            await export_selected_bibliography(
                async_db,
                user,
                item.workspace_id,
                [item.id, target_id],
                BibliographyFormat.bibtex,
            )


def test_builtin_style_catalog_is_searchable():
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

    monkeypatch.setattr(styles, "builtin_style_catalog", load_catalog)
    selection = citations.select_builtin_citation_styles("matching", limit=1, include="saved")
    assert catalog_calls == 1
    assert selection.matches == (catalog[0],)
    assert selection.included == catalog[1]


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["item", "selection", "workspace"])
async def test_bibliography_entry_points_share_export_options_and_download_headers(
    async_db, async_session_factory, tmp_path, monkeypatch, scope
):
    from test_http import authenticated_async_client

    from quirebase.core.config import get_settings

    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    item.work = {**item.work, "description": "An abstract that must be excluded."}
    await async_db.commit()
    base = f"/api/v1/workspaces/{item.workspace_id}"
    try:
        options = {"file_format": "bibtex", "include_abstract": False}
        if scope == "selection":
            response = await client.post(
                f"{base}/items/bibliography",
                json={"item_ids": [str(item.id)], **options},
            )
        else:
            path = (
                f"{base}/items/{item.id}/bibliography"
                if scope == "item"
                else f"{base}/bibliography"
            )
            response = await client.get(path, params=options)
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/x-bibtex; charset=utf-8"
        assert response.headers["cache-control"] == "private, no-store"
        assert ".bib" in response.headers["content-disposition"]
        assert "abstract" not in response.text
        assert "An abstract that must be excluded." not in response.text
        assert "title = {Paper}" in response.text
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["item", "selection", "workspace"])
async def test_bibliography_entry_points_reject_unsupported_formats(
    async_db, async_session_factory, tmp_path, monkeypatch, scope
):
    from test_http import authenticated_async_client

    from quirebase.core.config import get_settings

    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{item.workspace_id}"
    try:
        if scope == "selection":
            response = await client.post(
                f"{base}/items/bibliography",
                json={"item_ids": [str(item.id)], "file_format": "unsupported"},
            )
        else:
            path = (
                f"{base}/items/{item.id}/bibliography"
                if scope == "item"
                else f"{base}/bibliography"
            )
            response = await client.get(path, params={"file_format": "unsupported"})
        assert response.status_code == 422
        assert response.json()["code"] == "validation_failed"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_citation_style_search_includes_owned_custom_styles(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    from test_http import authenticated_async_client

    from quirebase.core.config import get_settings

    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        user = await db.get(User, item.created_by)
        xml = builtin_style_xml("apa")
        assert user is not None and xml is not None
        await create_custom_citation_style(
            db, user, fixture_workspace_id(user), "My Searchable Style", xml
        )
        response = await client.get(
            f"/api/v1/workspaces/{item.workspace_id}/citation-styles?query=searchable"
        )
        assert response.status_code == 200
        assert response.json()["styles"][0]["name"] == "My Searchable Style"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_citation_style_search_includes_requested_saved_style(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    from test_http import authenticated_async_client

    from quirebase.core.config import get_settings

    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.get(
            f"/api/v1/workspaces/{item.workspace_id}/citation-styles",
            params={"limit": 1, "include": "apa"},
        )
        assert response.status_code == 200
        styles = response.json()["styles"]
        assert len(styles) == 2
        assert styles[-1] == {"key": "apa", "name": "APA Style 7th edition", "scope": "builtin"}
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_item_to_csl_json_maps_reference_types(async_db):
    assert (
        work_to_csl_json((await _async_item(async_db, reference_type="book")).work)["type"]
        == "book"
    )
    assert (
        work_to_csl_json((await _async_item(async_db, reference_type="preprint")).work)["type"]
        == "article"
    )
    assert work_to_csl_json((await _async_item(async_db, reference_type="thesis")).work)["type"]
    assert (
        work_to_csl_json((await _async_item(async_db, reference_type="document")).work)["type"]
        == "document"
    )


@pytest.mark.anyio
async def test_author_names_without_commas_use_last_token_as_family(async_db):
    record = work_to_csl_json((await _async_item(async_db, authors="Ada Lovelace")).work)
    assert record["author"] == [{"family": "Lovelace", "given": "Ada"}]


@pytest.mark.anyio
async def test_builtin_styles_render(async_db):
    item = await _async_item(async_db)
    for style_key in ("apa", "ieee", "modern-language-association"):
        xml = builtin_style_xml(style_key)
        assert xml is not None, style_key
        rendered = render_citation(item.work, xml)
        assert "An Example Paper" in rendered


@pytest.mark.anyio
async def test_render_citation_html(async_db):
    item = await _async_item(async_db)
    apa_xml = builtin_style_xml("apa")
    assert apa_xml is not None
    rendered = render_citation(item.work, apa_xml, output_format="html")
    assert "An Example Paper" in rendered


@pytest.mark.anyio
async def test_resolve_style_xml_scoped_to_owner(async_db):
    db = async_db
    csl_xml = builtin_style_xml("apa")
    assert csl_xml is not None
    user_a = User(username="owner-a", password_hash="unused")
    user_b = User(username="owner-b", password_hash="unused")
    db.add_all([user_a, user_b])
    await db.flush()
    await provision_initial_workspace(db, user_a)
    await provision_initial_workspace(db, user_b)
    await db.commit()
    style_a = await create_custom_citation_style(
        db, user_a, fixture_workspace_id(user_a), "Custom A", csl_xml
    )
    assert (
        await resolve_style_xml(db, user_a, fixture_workspace_id(user_a), str(style_a.id))
        == csl_xml
    )
    assert (
        await resolve_style_xml(db, user_b, fixture_workspace_id(user_b), str(style_a.id)) is None
    )
    assert await resolve_style_xml(db, None, fixture_workspace_id(user_a), str(style_a.id)) is None
    assert await resolve_style_xml(db, user_a, fixture_workspace_id(user_a), "apa") == csl_xml
    assert await resolve_style_xml(db, user_b, fixture_workspace_id(user_b), "apa") == csl_xml
    assert await resolve_style_xml(db, None, fixture_workspace_id(user_a), "apa") == csl_xml


@pytest.mark.anyio
async def test_csl_export_preserves_unexpected_rendering_errors(async_db, monkeypatch):
    from quirebase.library import citations

    db = async_db
    item = await _async_item(db)
    user = await db.get(User, item.created_by)
    assert user is not None
    style = CitationStyle(
        workspace_id=item.workspace_id,
        name="Persisted Style",
        csl_xml="<style/>",
        created_by=user.id,
    )
    db.add(style)
    await db.flush()

    def rendering_failure(*_args, **_kwargs):
        raise RuntimeError("rendering failed")

    monkeypatch.setattr(citations, "render_bibliography", rendering_failure)
    with pytest.raises(RuntimeError, match="rendering failed"):
        await export_item_bibliography(
            db,
            user,
            item.workspace_id,
            item.id,
            BibliographyFormat.csl,
            style_key=str(style.id),
        )


@pytest.mark.anyio
async def test_citation_text_preserves_unexpected_rendering_errors(async_db, monkeypatch):
    from quirebase.library import citations

    db = async_db
    item = await _async_item(db)
    user = await db.get(User, item.created_by)
    assert user is not None
    style = CitationStyle(
        workspace_id=item.workspace_id,
        name="Persisted Style",
        csl_xml="<style/>",
        created_by=user.id,
    )
    db.add(style)
    await db.flush()

    def rendering_failure(*_args, **_kwargs):
        raise RuntimeError("rendering failed")

    monkeypatch.setattr(citations, "render_citation", rendering_failure)
    with pytest.raises(RuntimeError, match="rendering failed"):
        await render_item_citation(db, user, item.workspace_id, item.id, style_key=str(style.id))


@pytest.mark.anyio
async def test_citation_routes_enforce_custom_style_ownership(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    from test_http import authenticated_async_client

    from quirebase.core.config import get_settings

    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        user_a = await db.get(User, item.created_by)
        assert user_a is not None
        user_b = User(username="other-user", password_hash="unused")
        db.add(user_b)
        await db.flush()
        await provision_initial_workspace(db, user_b)
        await db.commit()
        csl_xml = builtin_style_xml("apa")
        assert csl_xml is not None
        style_a = await create_custom_citation_style(
            db, user_a, item.workspace_id, "User A Style", csl_xml
        )
        style_b = await create_custom_citation_style(
            db, user_b, fixture_workspace_id(user_b), "User B Style", csl_xml
        )
        res = await client.get(
            f"/api/v1/workspaces/{item.workspace_id}/items/{item.id}/citation?style={style_a.id}"
        )
        assert res.status_code == 200
        assert item.work.get("title") in res.json()["content"]
        res_forbidden = await client.get(
            f"/api/v1/workspaces/{item.workspace_id}/items/{item.id}/citation?style={style_b.id}"
        )
        assert res_forbidden.status_code == 422
        res_csl_forbidden = await client.get(
            f"/api/v1/workspaces/{item.workspace_id}/items/{item.id}/bibliography?file_format=csl&style={style_b.id}"
        )
        assert res_csl_forbidden.status_code == 422
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_custom_styles_accessible_in_item_sections(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    from test_http import authenticated_async_client

    from quirebase.core.config import get_settings

    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        user = await db.get(User, item.created_by)
        assert user is not None
        csl_xml = '<?xml version="1.0" encoding="utf-8"?>\n<style xmlns="http://purl.org/net/xbiblio/csl" version="1.0" class="in-text">\n  <info><id>test</id><title>Test Custom</title><updated>2025-01-01T00:00:00Z</updated></info>\n  <citation><layout><text variable="title"/></layout></citation>\n  <bibliography><layout><text variable="title"/></layout></bibliography>\n</style>'
        custom_style = await create_custom_citation_style(
            db, user, item.workspace_id, "My Isolated Custom Style", csl_xml
        )
        response = await client.get(
            f"/api/v1/workspaces/{item.workspace_id}/citation-styles",
            params={"include": custom_style.id},
        )
        assert response.status_code == 200
        assert any(
            style["key"] == str(custom_style.id) and style["scope"] == "custom"
            for style in response.json()["styles"]
        )
        text_res = await client.get(
            f"/api/v1/workspaces/{item.workspace_id}/items/{item.id}/citation?style={custom_style.id}"
        )
        assert text_res.status_code == 200
        assert item.work.get("title") in text_res.json()["content"]
    finally:
        await client.aclose()
        get_settings.cache_clear()
