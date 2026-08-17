from __future__ import annotations

from test_http import authenticated_client

from quirebase.core.config import get_settings
from quirebase.models import Item, ItemTag, Project, ProjectMember, Tag, User
from quirebase.web.app import app


def test_projects_have_a_dedicated_workspace(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        created = client.post(
            "/projects?csrf_token=test-csrf",
            data={"name": "Review queue"},
            follow_redirects=False,
        )
        project = db.query(Project).filter_by(name="Review queue").one()
        assert created.headers["location"] == f"/projects/{project.id}"
        listing = client.get("/projects")
        assert "创建项目" in listing.text
        assert "Review queue" in listing.text
        detail = client.get(f"/projects/{project.id}")
        assert "项目工作区" in detail.text
        assert db.get(ProjectMember, (project.id, item.created_by)).role == "owner"
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_tools_detect_duplicates_and_manage_owned_tags(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        duplicate = Item(title="Paper!", doi="10.1/same", created_by=item.created_by)
        item.doi = "10.1/same"
        tag = Tag(name="Old tag", created_by=item.created_by)
        db.add_all([duplicate, tag])
        db.flush()
        db.add(ItemTag(item_id=item.id, tag_id=tag.id))
        db.commit()

        tools = client.get("/tools?mode=doi")
        assert tools.status_code == 200
        assert "1 组可能重复项" in tools.text
        assert "Old tag" in tools.text
        assert f'href="/library?tag={tag.id}"' in tools.text

        # Verify clicking tag filter in library works by UUID and by name
        filtered_by_id = client.get(f"/library?tag={tag.id}")
        assert filtered_by_id.status_code == 200
        assert item.title in filtered_by_id.text

        filtered_by_name = client.get("/library?tag=Old%20tag")
        assert filtered_by_name.status_code == 200
        assert item.title in filtered_by_name.text

        orphan_tag = Tag(name="Orphan tag", created_by=item.created_by)
        db.add(orphan_tag)
        db.commit()

        tools_tags = client.get("/tools?tab=tags")
        assert tools_tags.status_code == 200
        assert "Orphan tag" in tools_tags.text
        assert "0 篇论文" in tools_tags.text

        renamed = client.post(
            f"/tools/tags/{tag.id}?csrf_token=test-csrf",
            data={"name": "Reviewed"},
            follow_redirects=False,
        )
        assert renamed.status_code == 303
        assert renamed.headers["location"] == "/tools?tab=tags#tags"
        db.refresh(tag)
        assert tag.name == "Reviewed"

        removed = client.post(
            f"/tools/tags/{tag.id}/delete?csrf_token=test-csrf",
            follow_redirects=False,
        )
        assert removed.status_code == 303
        assert removed.headers["location"] == "/tools?tab=tags#tags"
        assert db.get(Tag, tag.id) is None
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()


def test_security_and_admin_pages_use_workspace_layout(db, tmp_path, monkeypatch):
    client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    try:
        sessions = client.get("/account/sessions")
        assert sessions.status_code == 200
        assert "会话控制已启用" in sessions.text
        assert "当前设备" in sessions.text

        user = db.get(User, item.created_by)
        user.role = "administrator"
        db.commit()
        admin = client.get("/admin")
        assert admin.status_code == 200
        assert "系统工作区" in admin.text
        assert "邀请用户" in admin.text
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
