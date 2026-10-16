from uuid import uuid4

import pytest
from app_helpers import json_payload
from test_http import authenticated_async_client

from quirebase.core.config import get_settings
from quirebase.documents import create_document_annotation
from quirebase.documents.annotations import create_annotation_reply
from quirebase.documents.schemas import AnnotationCreate, AnnotationReplyCreate
from quirebase.models import User, WorkspaceMember, WorkspaceRole
from quirebase.projects import add_item_to_project, add_project_participant, create_project

pytestmark = [pytest.mark.anyio, pytest.mark.shared_postgres]


async def test_annotation_patch_cannot_change_the_audience_of_existing_replies(
    persistence_db, persistence_sessions, tmp_path, monkeypatch
):
    db = persistence_db
    client, item, revision = await authenticated_async_client(
        db, persistence_sessions, tmp_path, monkeypatch
    )
    try:
        owner = await db.get(User, item.created_by)
        source = await create_project(
            db, owner, item.workspace_id, "Source", participation="managed"
        )
        target = await create_project(
            db, owner, item.workspace_id, "Target", participation="managed"
        )
        await add_item_to_project(db, owner, item.workspace_id, source.id, item.id)
        await add_item_to_project(db, owner, item.workspace_id, target.id, item.id)
        responder = User(username="annotation-responder", password_hash="unused")
        db.add(responder)
        await db.flush()
        db.add(
            WorkspaceMember(
                workspace_id=item.workspace_id, user_id=responder.id, role=WorkspaceRole.editor
            )
        )
        await db.commit()
        await add_project_participant(db, owner, item.workspace_id, source.id, responder.username)
        payload = {"type": "note", "rect": {"x": 1, "y": 2, "width": 20, "height": 10}}
        annotation = await create_document_annotation(
            db,
            owner,
            item.workspace_id,
            item.id,
            AnnotationCreate(
                id=uuid4(),
                revision_id=revision.id,
                page_index=0,
                kind="note",
                scope="project",
                project_id=source.id,
                body="Original",
                payload=payload,
            ),
        )
        reply = await create_annotation_reply(
            db,
            responder,
            item.workspace_id,
            item.id,
            annotation["id"],
            AnnotationReplyCreate(id=uuid4(), body="Reply for source only"),
        )
        path = (
            f"/api/v1/workspaces/{item.workspace_id}/items/{item.id}/annotations/{annotation['id']}"
        )
        update = {
            "version": 1,
            "page_index": 0,
            "kind": "note",
            "body": "Updated",
            "payload": payload,
        }
        for extra in (
            {"scope": "private"},
            {"project_id": target.id},
            {"scope": "project", "project_id": target.id},
        ):
            response = await client.patch(path, json=json_payload(update | extra))
            assert response.status_code == 422
        response = await client.patch(path, json=update)
        assert response.status_code == 200
        result = response.json()
        assert result["scope"] == "project" and result["project_id"] == str(source.id)
        assert result["body"] == "Updated" and result["version"] == 2
        assert [(row["id"], row["body"]) for row in result["replies"]] == [
            (str(reply["id"]), "Reply for source only")
        ]
    finally:
        await client.aclose()
        get_settings.cache_clear()
