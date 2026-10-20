from __future__ import annotations

from uuid import uuid4

import pytest
from advanced_alchemy.types import FileObject
from app_helpers import json_payload
from sqlalchemy import select
from test_http import authenticated_async_client
from workspace_helpers import provision_initial_workspace

from quirebase.access import resolve_workspace_context
from quirebase.core.errors import (
    PermissionDenied,
    ProjectLifecycleError,
    ResourceUnavailable,
    ValidationFailure,
    WorkspaceLifecycleError,
)
from quirebase.library import BulkItemAction, apply_bulk_item_action
from quirebase.library.tags import list_accessible_tags_with_counts
from quirebase.models import (
    AuditEvent,
    FileRevision,
    Item,
    ItemTag,
    PdfAnnotation,
    PdfAnnotationReply,
    Project,
    ProjectItem,
    ProjectParticipation,
    ProjectState,
    Tag,
    User,
    WorkspaceMember,
    WorkspaceRole,
)
from quirebase.projects import remove_items_from_project, set_project_state
from quirebase.workspaces import archive_workspace


async def _context(db):
    owner = User(username=f"bulk-removal-{uuid4()}", password_hash="unused")
    db.add(owner)
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    items = [
        Item(
            workspace_id=workspace.id,
            created_by=owner.id,
            work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": f"Item {index}"},
        )
        for index in range(4)
    ]
    project = Project(
        workspace_id=workspace.id,
        created_by=owner.id,
        name="Working set",
        participation=ProjectParticipation.workspace,
    )
    tag = Tag(workspace_id=workspace.id, created_by=owner.id, name="Methods")
    db.add_all([*items, project, tag])
    await db.flush()
    for item in items:
        db.add(
            ProjectItem(
                workspace_id=workspace.id,
                project_id=project.id,
                item_id=item.id,
                added_by=owner.id,
            )
        )
        db.add(ItemTag(workspace_id=workspace.id, item_id=item.id, tag_id=tag.id))
    await db.commit()
    return owner, workspace, items, project, tag


@pytest.mark.anyio
async def test_bulk_remove_tag_is_idempotent_scoped_and_refreshes_counts(async_db):
    owner, workspace, items, _project, tag = await _context(async_db)
    other_tag = Tag(workspace_id=workspace.id, created_by=owner.id, name="Keep")
    async_db.add(other_tag)
    await async_db.flush()
    async_db.add(ItemTag(workspace_id=workspace.id, item_id=items[0].id, tag_id=other_tag.id))
    await async_db.commit()

    for _ in range(2):
        await apply_bulk_item_action(
            async_db,
            owner,
            workspace.id,
            [items[1].id, items[0].id, items[1].id],
            BulkItemAction.remove_tag,
            tag_id=tag.id,
        )
        assignments = set(
            (await async_db.execute(select(ItemTag.item_id, ItemTag.tag_id))).tuples()
        )
        assert assignments == {
            (items[0].id, other_tag.id),
            (items[2].id, tag.id),
            (items[3].id, tag.id),
        }
    context = await resolve_workspace_context(async_db, owner, workspace.id)
    tags, total = await list_accessible_tags_with_counts(async_db, context)
    assert total == 2
    assert {record.id: count for record, count in tags} == {tag.id: 2, other_tag.id: 1}
    events = list(
        await async_db.scalars(
            select(AuditEvent).where(AuditEvent.action == "library.bulk.remove_tag")
        )
    )
    assert len(events) == 2
    assert events[0].detail == json_payload({
        "item_ids": [items[1].id, items[0].id],
        "tag_id": tag.id,
    })
    assert events[0].authorization_resource_action == "tag.use"
    assert await async_db.get(Tag, tag.id) is not None


@pytest.mark.anyio
async def test_bulk_project_removal_preserves_items_files_and_other_annotation_scopes(async_db):
    owner, workspace, items, project, _tag = await _context(async_db)
    other_project = Project(
        workspace_id=workspace.id,
        created_by=owner.id,
        name="Other context",
        participation=ProjectParticipation.workspace,
    )
    async_db.add(other_project)
    await async_db.flush()
    other_link = ProjectItem(
        workspace_id=workspace.id,
        project_id=other_project.id,
        item_id=items[0].id,
        added_by=owner.id,
    )
    async_db.add(other_link)
    await async_db.flush()
    selected_links = list(
        await async_db.scalars(
            select(ProjectItem)
            .where(ProjectItem.project_id == project.id)
            .order_by(ProjectItem.item_id)
        )
    )
    annotations = []
    revisions = []
    for link in [*selected_links, other_link]:
        revision = FileRevision(
            workspace_id=workspace.id,
            item_id=link.item_id,
            created_by=owner.id,
            processing_state="ready",
            file=FileObject(
                backend="documents",
                filename=f"{uuid4()}.pdf",
                size=100,
                content_type="application/pdf",
            ),
        )
        async_db.add(revision)
        await async_db.flush()
        revisions.append(revision)
        annotation = PdfAnnotation(
            workspace_id=workspace.id,
            file_revision_id=revision.id,
            item_id=link.item_id,
            page_index=0,
            author_id=owner.id,
            kind="note",
            scope="project",
            project_item_id=link.id,
            payload={},
        )
        annotations.append(annotation)
    private_annotation = PdfAnnotation(
        workspace_id=workspace.id,
        file_revision_id=revisions[0].id,
        item_id=revisions[0].item_id,
        page_index=0,
        author_id=owner.id,
        kind="note",
        scope="private",
        payload={},
    )
    annotations.append(private_annotation)
    async_db.add_all(annotations)
    await async_db.flush()
    replies = [
        PdfAnnotationReply(
            workspace_id=workspace.id,
            annotation_id=annotation.id,
            author_id=owner.id,
            body="Context reply",
        )
        for annotation in annotations
    ]
    async_db.add_all(replies)
    await async_db.commit()
    removed_items = {items[0].id, items[1].id}
    removed_annotation_ids = {
        annotation.id
        for annotation in annotations
        if annotation.item_id in removed_items
        and annotation.project_item_id in {link.id for link in selected_links}
    }

    for _ in range(2):
        await apply_bulk_item_action(
            async_db,
            owner,
            workspace.id,
            [items[1].id, items[0].id],
            BulkItemAction.remove_project,
            project_id=project.id,
        )
    assert set(await async_db.scalars(select(Item.id))) == {item.id for item in items}
    assert set(await async_db.scalars(select(FileRevision.id))) == {
        revision.id for revision in revisions
    }
    assert (
        set(await async_db.scalars(select(PdfAnnotation.id)))
        == {annotation.id for annotation in annotations} - removed_annotation_ids
    )
    assert set(await async_db.scalars(select(PdfAnnotationReply.id))) == {
        reply.id for reply in replies if reply.annotation_id not in removed_annotation_ids
    }
    assert set(await async_db.scalars(select(ProjectItem.id))) == {
        link.id for link in [*selected_links, other_link] if link.item_id not in removed_items
    } | {other_link.id}
    event = await async_db.scalar(
        select(AuditEvent).where(AuditEvent.action == "library.bulk.remove_project")
    )
    assert event is not None
    assert event.project_id == project.id
    assert event.authorization_resource_action == "project_item.manage"
    assert event.detail == json_payload({
        "item_ids": [items[1].id, items[0].id],
        "project_id": project.id,
    })


@pytest.mark.anyio
@pytest.mark.parametrize("action", [BulkItemAction.remove_tag, BulkItemAction.remove_project])
async def test_bulk_removal_rejects_mixed_workspace_items_before_changing_any_links(
    async_db, action
):
    owner, workspace, items, project, tag = await _context(async_db)
    (
        _foreign_owner,
        _foreign_workspace,
        foreign_items,
        _foreign_project,
        _foreign_tag,
    ) = await _context(async_db)
    with pytest.raises(ValidationFailure):
        await apply_bulk_item_action(
            async_db,
            owner,
            workspace.id,
            [items[0].id, foreign_items[0].id],
            action,
            project_id=project.id,
            tag_id=tag.id,
        )
    assert len(list(await async_db.scalars(select(ItemTag.item_id)))) == 8
    assert len(list(await async_db.scalars(select(ProjectItem.id)))) == 8
    assert not list(
        await async_db.scalars(select(AuditEvent).where(AuditEvent.action.like("library.bulk.%")))
    )


@pytest.mark.anyio
@pytest.mark.parametrize("action", [BulkItemAction.remove_tag, BulkItemAction.remove_project])
async def test_bulk_removal_rejects_foreign_or_missing_target_without_changes(async_db, action):
    owner, workspace, items, _project, _tag = await _context(async_db)
    (
        _foreign_owner,
        _foreign_workspace,
        _foreign_items,
        foreign_project,
        foreign_tag,
    ) = await _context(async_db)
    for project_id, tag_id in [(foreign_project.id, foreign_tag.id), (uuid4(), uuid4())]:
        with pytest.raises(ResourceUnavailable):
            await apply_bulk_item_action(
                async_db,
                owner,
                workspace.id,
                [items[0].id],
                action,
                project_id=project_id,
                tag_id=tag_id,
            )
    assert len(list(await async_db.scalars(select(ItemTag.item_id)))) == 8
    assert len(list(await async_db.scalars(select(ProjectItem.id)))) == 8


@pytest.mark.anyio
@pytest.mark.parametrize("action", [BulkItemAction.remove_tag, BulkItemAction.remove_project])
async def test_bulk_removal_rejects_viewer_and_read_only_workspace(async_db, action):
    owner, workspace, items, project, tag = await _context(async_db)
    viewer = User(username=f"viewer-{uuid4()}", password_hash="unused")
    async_db.add(viewer)
    await async_db.flush()
    async_db.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=viewer.id, role=WorkspaceRole.viewer)
    )
    await async_db.commit()
    with pytest.raises(PermissionDenied):
        await apply_bulk_item_action(
            async_db,
            viewer,
            workspace.id,
            [items[0].id],
            action,
            project_id=project.id,
            tag_id=tag.id,
        )
    await archive_workspace(async_db, owner, workspace.id)
    with pytest.raises(WorkspaceLifecycleError):
        await apply_bulk_item_action(
            async_db,
            owner,
            workspace.id,
            [items[0].id],
            action,
            project_id=project.id,
            tag_id=tag.id,
        )
    assert len(list(await async_db.scalars(select(ItemTag.item_id)))) == 4
    assert len(list(await async_db.scalars(select(ProjectItem.id)))) == 4


@pytest.mark.anyio
async def test_bulk_project_removal_rechecks_archived_and_hidden_project(async_db):
    owner, workspace, items, project, _tag = await _context(async_db)
    await set_project_state(async_db, owner, workspace.id, project.id, ProjectState.archived)
    with pytest.raises(ProjectLifecycleError):
        await apply_bulk_item_action(
            async_db,
            owner,
            workspace.id,
            [items[0].id],
            BulkItemAction.remove_project,
            project_id=project.id,
        )
    project.state = ProjectState.active
    project.participation = ProjectParticipation.managed
    editor = User(username="hidden-project-editor", password_hash="unused")
    async_db.add(editor)
    await async_db.flush()
    async_db.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=editor.id, role=WorkspaceRole.editor)
    )
    await async_db.commit()
    with pytest.raises(ResourceUnavailable):
        await apply_bulk_item_action(
            async_db,
            editor,
            workspace.id,
            [items[0].id],
            BulkItemAction.remove_project,
            project_id=project.id,
        )
    assert len(list(await async_db.scalars(select(ProjectItem.id)))) == 4


@pytest.mark.anyio
async def test_projects_batch_removal_validates_entire_selection_before_detaching(async_db):
    owner, workspace, items, project, _tag = await _context(async_db)
    with pytest.raises(ResourceUnavailable):
        await remove_items_from_project(
            async_db, owner, workspace.id, project.id, [items[0].id, uuid4()]
        )
    assert len(list(await async_db.scalars(select(ProjectItem.id)))) == 4


@pytest.mark.anyio
async def test_bulk_http_contract_rejects_legacy_actions_and_irrelevant_fields(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, item, _revision = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    project = Project(
        workspace_id=item.workspace_id,
        created_by=item.created_by,
        name="HTTP working set",
        participation=ProjectParticipation.workspace,
    )
    tag = Tag(workspace_id=item.workspace_id, created_by=item.created_by, name="HTTP Tag")
    async_db.add_all([project, tag])
    await async_db.flush()
    async_db.add_all([
        ProjectItem(workspace_id=item.workspace_id, item_id=item.id, project_id=project.id),
        ItemTag(workspace_id=item.workspace_id, item_id=item.id, tag_id=tag.id),
    ])
    await async_db.commit()
    path = f"/api/v1/workspaces/{item.workspace_id}/items/bulk"
    for payload in [
        {},
        {"action": "project_add", "project_id": project.id},
        {"action": "tag", "tag_name": "Legacy Tag"},
        {"action": "delete"},
        {"action": "copy_bibliography"},
        {"action": "unknown"},
        {"action": "add_project"},
        {"action": "add_tag"},
        {"action": "add_tag", "tag_name": ""},
        {"action": "remove_tag"},
        {"action": "remove_project"},
        {"action": "remove_project", "project_id": project.id, "confirmation": "remove_project"},
        {"action": "delete_items", "confirmation": "delete"},
        {"action": "add_project", "project_id": project.id, "tag_id": tag.id},
        {"action": "add_tag", "tag_name": "Extra fields", "project_id": project.id},
        {"action": "remove_tag", "tag_id": tag.id, "tag_name": "Extra fields"},
        {"action": "delete_items", "project_id": project.id},
        {"action": "remove_tag", "tag_id": tag.id, "item_ids": []},
        {"action": "delete_items", "item_ids": []},
    ]:
        response = await client.post(path, json=json_payload({"item_ids": [item.id], **payload}))
        assert response.status_code == 422
        assert response.json()["code"] == "validation_failed"
    assert len(list(await async_db.scalars(select(ProjectItem.id)))) == 1
    assert len(list(await async_db.scalars(select(ItemTag.item_id)))) == 1
    assert not list(
        await async_db.scalars(select(AuditEvent).where(AuditEvent.action.like("library.bulk.%")))
    )

    response = await client.post(
        path,
        json=json_payload({"item_ids": [item.id], "action": "remove_tag", "tag_id": tag.id}),
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    response = await client.post(
        path,
        json=json_payload({
            "item_ids": [item.id],
            "action": "remove_project",
            "project_id": project.id,
        }),
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not list(await async_db.scalars(select(ProjectItem.id)))
    assert not list(await async_db.scalars(select(ItemTag.item_id)))
    await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["project_add", "tag", "delete", "copy_bibliography"])
async def test_bulk_domain_rejects_removed_and_unknown_actions_without_side_effects(
    async_db, action
):
    owner, workspace, items, project, tag = await _context(async_db)
    with pytest.raises(ValidationFailure, match="unknown bulk action"):
        await apply_bulk_item_action(
            async_db,
            owner,
            workspace.id,
            [items[0].id],
            action,
            project_id=project.id,
            tag_name="Rejected Tag",
            tag_id=tag.id,
        )
    assert len(list(await async_db.scalars(select(Item.id)))) == 4
    assert len(list(await async_db.scalars(select(ItemTag.item_id)))) == 4
    assert len(list(await async_db.scalars(select(ProjectItem.id)))) == 4
    assert not list(
        await async_db.scalars(select(AuditEvent).where(AuditEvent.action.like("library.bulk.%")))
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("action", "options"),
    [
        (BulkItemAction.add_project, {}),
        (BulkItemAction.remove_project, {}),
        (BulkItemAction.add_tag, {"tag_name": "  "}),
        (BulkItemAction.remove_tag, {}),
    ],
)
async def test_bulk_domain_keeps_configuration_validation(async_db, action, options):
    owner, workspace, items, _project, _tag = await _context(async_db)
    with pytest.raises(ValidationFailure):
        await apply_bulk_item_action(
            async_db, owner, workspace.id, [items[0].id], action, **options
        )
    assert len(list(await async_db.scalars(select(Item.id)))) == 4
    assert len(list(await async_db.scalars(select(ItemTag.item_id)))) == 4
    assert len(list(await async_db.scalars(select(ProjectItem.id)))) == 4
    assert not list(
        await async_db.scalars(select(AuditEvent).where(AuditEvent.action.like("library.bulk.%")))
    )


@pytest.mark.anyio
@pytest.mark.parametrize("action", list(BulkItemAction))
async def test_bulk_domain_rejects_empty_selection_before_any_changes(async_db, action):
    owner, workspace, items, project, tag = await _context(async_db)
    with pytest.raises(ValidationFailure, match="select one or more accessible Items"):
        await apply_bulk_item_action(
            async_db,
            owner,
            workspace.id,
            [],
            action,
            project_id=project.id,
            tag_name="Rejected Tag",
            tag_id=tag.id,
        )
    assert set(await async_db.scalars(select(Item.id))) == {item.id for item in items}
    assert len(list(await async_db.scalars(select(ItemTag.item_id)))) == 4
    assert len(list(await async_db.scalars(select(ProjectItem.id)))) == 4
    assert not list(
        await async_db.scalars(select(AuditEvent).where(AuditEvent.action.like("library.bulk.%")))
    )
