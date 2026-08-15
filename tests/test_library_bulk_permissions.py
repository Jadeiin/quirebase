from __future__ import annotations

import json

import pytest
from sqlalchemy import select
from test_http import authenticated_client

from quirebase.core.crypto import hash_password
from quirebase.core.errors import PermissionDenied
from quirebase.library import bulk_action, bulk_download_pdfs
from quirebase.models import AuditEvent, Item, Project, ProjectItem, ProjectMember, User


def test_bulk_action_blocks_unauthorized_assignment_to_project(db, tmp_path, monkeypatch):
    _client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)

    # Owner of target project, but viewer of source project where item resides
    viewer_user = User(
        username="viewer_user",
        password_hash=hash_password("password1234"),
        role="member",
    )
    db.add(viewer_user)
    db.flush()

    # Source project where item is shared and viewer is a viewer
    source_project = Project(name="Source Project", created_by=item.created_by)
    db.add(source_project)
    db.flush()
    db.add(ProjectItem(project_id=source_project.id, item_id=item.id))
    db.add(ProjectMember(project_id=source_project.id, user_id=viewer_user.id, role="viewer"))

    # Target project owned by viewer
    target_project = Project(name="Target Project", created_by=viewer_user.id)
    db.add(target_project)
    db.flush()
    db.add(ProjectMember(project_id=target_project.id, user_id=viewer_user.id, role="owner"))
    db.commit()

    # Attempt to bulk-assign item to target project as viewer_user
    with pytest.raises(PermissionDenied, match="all selected items must be editable"):
        bulk_action(
            db,
            viewer_user,
            item_ids=[item.id],
            action="add_project",
            project_id=target_project.id,
        )

    # Verify no unauthorized ProjectItem was created
    assignment = db.get(ProjectItem, (target_project.id, item.id))
    assert assignment is None


def test_bulk_action_records_single_bulk_audit_event(db, tmp_path, monkeypatch):
    _client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    owner = db.get(User, item.created_by)

    target_project = Project(name="My Project", created_by=owner.id)
    db.add(target_project)
    db.flush()
    db.add(ProjectMember(project_id=target_project.id, user_id=owner.id, role="owner"))
    db.commit()

    bulk_action(
        db,
        owner,
        item_ids=[item.id],
        action="add_project",
        project_id=target_project.id,
    )

    event = db.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "library.bulk.add_project")
        .order_by(AuditEvent.created_at.desc())
    )
    assert event is not None
    assert json.loads(event.detail)["item_ids"] == [item.id]


def test_bulk_download_pdfs_records_audit_event(db, tmp_path, monkeypatch):
    _client, item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    owner = db.get(User, item.created_by)

    archive = bulk_download_pdfs(db, owner, [item.id])
    assert archive.getvalue()

    event = db.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "library.bulk.download_pdfs")
        .order_by(AuditEvent.created_at.desc())
    )
    assert event is not None
    assert json.loads(event.detail)["item_ids"] == [item.id]


def test_bulk_export_rejects_inaccessible_items(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    other_user = User(username="private_owner", password_hash="test-hash", role="member")
    db.add(other_user)
    db.flush()
    private_item = Item(title="Private metadata", created_by=other_user.id)
    db.add(private_item)
    db.commit()

    response = client.post(
        "/library/bulk?csrf_token=test-csrf",
        data={"action": "export_bibtex", "item_ids": private_item.id},
    )

    assert response.status_code == 422
    assert "Private metadata" not in response.text
