from __future__ import annotations

import pytest
from sqlalchemy import select
from test_http import authenticated_async_client

from quirebase.core.config import get_settings
from quirebase.models import Item, ItemTag, Project, ProjectMember, Tag, User


@pytest.mark.anyio
async def test_projects_have_a_dedicated_workspace(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        created = await client.post(
            "/api/v1/projects",
            json={"name": "Review queue"},
        )
        project = await db.scalar(select(Project).where(Project.name == "Review queue"))
        assert project is not None
        assert created.status_code == 201
        assert created.json()["id"] == project.id
        listing = await client.get("/api/v1/projects")
        assert [row["name"] for row in listing.json()] == ["Review queue"]
        detail = await client.get(f"/api/v1/projects/{project.id}")
        assert detail.json()["name"] == "Review queue"
        updated = await client.patch(
            f"/api/v1/projects/{project.id}",
            json={
                "name": "Review complete",
                "description": "Reviewed together",
                "visibility": "public",
            },
        )
        assert updated.status_code == 200
        refreshed = await client.get(f"/api/v1/projects/{project.id}")
        assert {key: refreshed.json()[key] for key in ("name", "description", "visibility")} == {
            "name": "Review complete",
            "description": "Reviewed together",
            "visibility": "public",
        }
        membership = await db.get(ProjectMember, (project.id, item.created_by))
        assert membership is not None
        assert membership.role == "owner"
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_tools_detect_duplicates_and_manage_owned_tags(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        duplicate = Item(title="Paper!", doi="10.1/same", created_by=item.created_by)
        item.doi = "10.1/same"
        tag = Tag(name="Old tag", created_by=item.created_by)
        db.add_all([duplicate, tag])
        await db.flush()
        db.add(ItemTag(item_id=item.id, tag_id=tag.id))
        await db.commit()

        tools = await client.get("/api/v1/duplicates?mode=doi")
        assert tools.status_code == 200
        assert len(tools.json()["groups"]) == 1
        assert {row["id"] for row in tools.json()["groups"][0]} == {item.id, duplicate.id}
        invalid_mode = await client.get("/api/v1/duplicates?mode=unknown")
        assert invalid_mode.status_code == 422
        tags = await client.get("/api/v1/tags")
        assert tags.json()[0]["name"] == "Old tag"
        assert tags.json()[0]["accessible_item_count"] == 1

        # The Library API accepts Tag UUIDs and names.
        filtered_by_id = await client.get("/api/v1/items", params={"tag": tag.id})
        assert filtered_by_id.status_code == 200
        assert [row["id"] for row in filtered_by_id.json()["items"]] == [item.id]

        filtered_by_name = await client.get("/api/v1/items", params={"tag": "Old tag"})
        assert filtered_by_name.status_code == 200
        assert [row["id"] for row in filtered_by_name.json()["items"]] == [item.id]

        orphan_tag = Tag(name="Orphan tag", created_by=item.created_by)
        db.add(orphan_tag)
        await db.commit()

        tools_tags = await client.get("/api/v1/tags")
        assert tools_tags.status_code == 200
        assert (
            next(row for row in tools_tags.json() if row["name"] == "Orphan tag")[
                "accessible_item_count"
            ]
            == 0
        )

        target_tag = Tag(name="Reviewed topic", created_by=item.created_by)
        db.add(target_tag)
        await db.commit()
        merged = await client.post(
            "/api/v1/tags/merge",
            json={
                "source_tag_id": tag.id,
                "target_tag_id": target_tag.id,
            },
        )
        assert merged.status_code == 200
        assert await db.get(Tag, tag.id) is None
        assert await db.get(ItemTag, (item.id, target_tag.id)) is not None

        renamed = await client.patch(
            f"/api/v1/tags/{target_tag.id}",
            json={"name": "Reviewed"},
        )
        assert renamed.status_code == 200
        await db.refresh(target_tag)
        assert target_tag.name == "Reviewed"

        removed = await client.delete(f"/api/v1/tags/{target_tag.id}")
        assert removed.status_code == 200
        assert await db.get(Tag, target_tag.id) is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_account_and_admin_workspace_apis(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        sessions = await client.get("/api/v1/account")
        assert sessions.status_code == 200
        assert len(sessions.json()["sessions"]) == 1
        assert sessions.json()["sessions"][0]["current"] is True

        user = await db.get(User, item.created_by)
        assert user is not None
        user.role = "administrator"
        await db.commit()
        admin = await client.get("/api/v1/admin/overview")
        assert admin.status_code == 200
        assert admin.json()["user_count"] == 1
        assert admin.json()["pending_invitation_count"] == 0
    finally:
        await client.aclose()
        get_settings.cache_clear()
