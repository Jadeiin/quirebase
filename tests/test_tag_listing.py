from __future__ import annotations

import pytest
from app_helpers import authenticated_async_client
from workspace_helpers import provision_initial_workspace

from quirebase.core.config import get_settings
from quirebase.models import ItemTag, Tag, User


@pytest.mark.anyio
async def test_tag_listing_pages_searches_and_resolves_selected_tags(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        tags = [
            Tag(workspace_id=item.workspace_id, created_by=item.created_by, name=f"Tag {n:03}")
            for n in range(101)
        ]
        special = Tag(
            workspace_id=item.workspace_id, created_by=item.created_by, name="Straße %_ Methods"
        )
        db.add_all([*tags, special])
        await db.flush()
        db.add(ItemTag(workspace_id=item.workspace_id, item_id=item.id, tag_id=tags[25].id))
        other_user = User(username="other-tag-owner", password_hash="unused")
        db.add(other_user)
        await db.flush()
        other_workspace = await provision_initial_workspace(db, other_user)
        foreign_tag = Tag(
            workspace_id=other_workspace.id, created_by=other_user.id, name="Tag foreign"
        )
        db.add(foreign_tag)
        await db.commit()
        path = f"/api/v1/workspaces/{item.workspace_id}/tags"

        first = (await client.get(path)).json()
        assert (first["total"], first["limit"], first["offset"]) == (102, 25, 0)
        assert len(first["items"]) == 25
        assert first["items"][0]["name"] == special.name
        second = (await client.get(path, params={"offset": 25, "limit": 20})).json()
        assert len(second["items"]) == 20
        assert {row["id"] for row in first["items"]}.isdisjoint(
            row["id"] for row in second["items"]
        )
        assigned = next(row for row in second["items"] if row["id"] == str(tags[25].id))
        assert assigned["accessible_item_count"] == 1
        assert any(row["accessible_item_count"] == 0 for row in second["items"])
        empty = (await client.get(path, params={"offset": 200})).json()
        assert empty["items"] == []
        assert empty["total"] == 102

        for search in ("STRASSE", "%", "_"):
            result = (await client.get(path, params={"search": search})).json()
            assert result["total"] == 1
            assert result["items"][0]["id"] == str(special.id)
        selected = (await client.get(path, params={"tag_id": str(tags[-1].id)})).json()
        assert selected["total"] == 1
        assert selected["items"][0]["id"] == str(tags[-1].id)
        foreign = (await client.get(path, params={"tag_id": str(foreign_tag.id)})).json()
        assert foreign["items"] == []
        assert foreign["total"] == 0
        for params in ({"limit": 101}, {"limit": 0}, {"offset": -1}):
            assert (await client.get(path, params=params)).status_code == 422
    finally:
        await client.aclose()
        get_settings.cache_clear()
