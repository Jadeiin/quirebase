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
            "/projects",
            data={"csrf_token": "test-csrf", "name": "Review queue"},
            follow_redirects=False,
        )
        project = await db.scalar(select(Project).where(Project.name == "Review queue"))
        assert project is not None
        assert created.headers["location"] == f"/projects/{project.id}"
        listing = await client.get("/projects")
        assert "创建项目" in listing.text
        assert "Review queue" in listing.text
        detail = await client.get(f"/projects/{project.id}")
        assert "项目工作区" in detail.text
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

        tools = await client.get("/tools?mode=doi")
        assert tools.status_code == 200
        assert "1 组可能重复项" in tools.text
        assert "Old tag" in tools.text
        assert f'href="/library?tag={tag.id}"' in tools.text

        # Verify clicking tag filter in library works by UUID and by name
        filtered_by_id = await client.get(f"/library?tag={tag.id}")
        assert filtered_by_id.status_code == 200
        assert item.title in filtered_by_id.text

        filtered_by_name = await client.get("/library?tag=Old%20tag")
        assert filtered_by_name.status_code == 200
        assert item.title in filtered_by_name.text

        orphan_tag = Tag(name="Orphan tag", created_by=item.created_by)
        db.add(orphan_tag)
        await db.commit()

        tools_tags = await client.get("/tools?tab=tags")
        assert tools_tags.status_code == 200
        assert "Orphan tag" in tools_tags.text
        assert "0 篇论文" in tools_tags.text

        target_tag = Tag(name="Reviewed topic", created_by=item.created_by)
        db.add(target_tag)
        await db.commit()
        tools_tags = await client.get("/tools?tab=tags")
        assert 'action="/tools/tags/merge' in tools_tags.text
        merged = await client.post(
            "/tools/tags/merge",
            data={
                "csrf_token": "test-csrf",
                "source_tag_id": tag.id,
                "target_tag_id": target_tag.id,
            },
            follow_redirects=False,
        )
        assert merged.status_code == 303
        assert await db.get(Tag, tag.id) is None
        assert await db.get(ItemTag, (item.id, target_tag.id)) is not None

        renamed = await client.post(
            f"/tools/tags/{target_tag.id}",
            data={"csrf_token": "test-csrf", "name": "Reviewed"},
            follow_redirects=False,
        )
        assert renamed.status_code == 303
        assert renamed.headers["location"] == "/tools?tab=tags#tags"
        await db.refresh(target_tag)
        assert target_tag.name == "Reviewed"

        removed = await client.post(
            f"/tools/tags/{target_tag.id}/delete",
            data={"csrf_token": "test-csrf"},
            follow_redirects=False,
        )
        assert removed.status_code == 303
        assert removed.headers["location"] == "/tools?tab=tags#tags"
        assert await db.get(Tag, target_tag.id) is None
    finally:
        await client.aclose()
        get_settings.cache_clear()


@pytest.mark.anyio
async def test_security_and_admin_pages_use_workspace_layout(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _revision = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        sessions = await client.get("/account/sessions")
        assert sessions.status_code == 200
        assert "会话控制已启用" in sessions.text
        assert "当前设备" in sessions.text

        user = await db.get(User, item.created_by)
        assert user is not None
        user.role = "administrator"
        await db.commit()
        admin = await client.get("/admin")
        assert admin.status_code == 200
        assert "系统工作区" in admin.text
        assert "邀请用户" in admin.text
    finally:
        await client.aclose()
        get_settings.cache_clear()
