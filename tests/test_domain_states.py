from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError

from quirebase.access.annotations import can_edit_annotation, editable_annotation_reply_ids
from quirebase.core.errors import ValidationFailure, VersionConflict
from quirebase.documents.annotations import (
    _annotation_views,
    create_annotation_reply,
    create_document_annotation,
    update_document_annotation,
    validate_payload,
)
from quirebase.documents.schemas import (
    AnnotationCreate,
    AnnotationReplyCreate,
    AnnotationUpdate,
)
from quirebase.models import (
    AnnotationKind,
    AnnotationScope,
    AuditEvent,
    FileRevision,
    FileRevisionProcessingState,
    Item,
    PdfAnnotation,
    PdfAnnotationObject,
    PdfAnnotationReply,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectRole,
    SystemRole,
    User,
)
from quirebase.projects.members import (
    ProjectMemberConflict,
    add_project_member,
    remove_project_member,
)
from quirebase.projects.workspaces import create_project, open_project_workspace


async def state_records(db):
    user = User(username="state-owner", password_hash="unused")
    db.add(user)
    await db.flush()
    item = Item(title="State constraints", created_by=user.id)
    project = Project(name="State project", created_by=user.id)
    db.add_all([item, project])
    await db.flush()
    member = ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.owner)
    revision = FileRevision(
        item_id=item.id,
        object_key="state.pdf",
        size=1,
        original_name="state.pdf",
        created_by=user.id,
    )
    db.add_all([member, revision])
    await db.flush()
    annotation = PdfAnnotation(
        file_revision_id=revision.id,
        page_index=0,
        author_id=user.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.private,
        payload={
            "type": "note",
            "rect": {"x": 1, "y": 2, "width": 24, "height": 24},
            "style": {},
        },
    )
    db.add(annotation)
    await db.commit()
    return member, revision, annotation, project


async def assert_rejected(db, statement: str, parameters: dict[str, str]) -> None:
    with pytest.raises(IntegrityError):
        await db.execute(text(statement), parameters)
    await db.rollback()


@pytest.mark.anyio
async def test_annotation_object_ids_are_atomic_across_roots_and_replies(
    async_session_factory,
):
    async with async_session_factory() as db:
        user = User(username="annotation-id-race", password_hash="unused")
        db.add(user)
        await db.flush()
        item = Item(title="Annotation ID race", created_by=user.id)
        db.add(item)
        await db.flush()
        revision = FileRevision(
            item_id=item.id,
            object_key="annotation-id-race.pdf",
            size=1,
            original_name="annotation-id-race.pdf",
            created_by=user.id,
            page_count=1,
            page_geometry="[[0, 0, 100, 100]]",
            processing_state=FileRevisionProcessingState.ready,
        )
        db.add(revision)
        await db.flush()
        parent = PdfAnnotation(
            file_revision_id=revision.id,
            page_index=0,
            author_id=user.id,
            kind=AnnotationKind.note,
            scope=AnnotationScope.private,
            payload={"type": "note", "rect": {"x": 1, "y": 2, "width": 24, "height": 24}},
        )
        db.add(parent)
        await db.commit()
        user_id, item_id, revision_id, parent_id = user.id, item.id, revision.id, parent.id

    shared_id = uuid4()

    async def create_root():
        async with async_session_factory() as db:
            user = await db.get(User, user_id)
            assert user is not None
            return await create_document_annotation(
                db,
                user,
                item_id,
                AnnotationCreate(
                    id=shared_id,
                    revision_id=revision_id,
                    page_index=0,
                    kind=AnnotationKind.note,
                    payload={
                        "type": "note",
                        "rect": {"x": 10, "y": 10, "width": 24, "height": 24},
                    },
                ),
            )

    async def create_reply():
        async with async_session_factory() as db:
            user = await db.get(User, user_id)
            assert user is not None
            return await create_annotation_reply(
                db,
                user,
                item_id,
                parent_id,
                AnnotationReplyCreate(id=shared_id, body="Racing reply"),
            )

    results = await asyncio.gather(create_root(), create_reply(), return_exceptions=True)

    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, VersionConflict) for result in results) == 1
    async with async_session_factory() as db:
        assert await db.get(PdfAnnotationObject, str(shared_id)) is not None
        roots = await db.scalar(select(PdfAnnotation.id).where(PdfAnnotation.id == str(shared_id)))
        replies = await db.scalar(
            select(PdfAnnotationReply.id).where(PdfAnnotationReply.id == str(shared_id))
        )
        assert (roots is not None) != (replies is not None)


@pytest.mark.anyio
async def test_closed_domain_states_are_loaded_as_domain_types(async_db):
    db = async_db
    member, revision, annotation, _project = await state_records(db)
    keys = (member.project_id, member.user_id, revision.id, annotation.id)

    db.expunge_all()

    loaded_member = await db.get(ProjectMember, keys[:2])
    loaded_revision = await db.get(FileRevision, keys[2])
    loaded_annotation = await db.get(PdfAnnotation, keys[3])
    assert loaded_member is not None and loaded_member.role is ProjectRole.owner
    assert loaded_revision is not None
    assert loaded_revision.processing_state is FileRevisionProcessingState.pending
    assert loaded_annotation is not None and loaded_annotation.kind is AnnotationKind.note
    assert loaded_annotation.scope is AnnotationScope.private


@pytest.mark.anyio
async def test_underline_is_an_allowed_annotation_kind(async_db):
    db = async_db
    _member, _revision, annotation, _project = await state_records(db)
    annotation_id = annotation.id

    await db.execute(
        text("UPDATE pdf_annotations SET kind = 'underline' WHERE id = :id"),
        {"id": annotation.id},
    )
    await db.commit()
    db.expunge_all()

    loaded = await db.get(PdfAnnotation, annotation_id)
    assert loaded is not None and loaded.kind is AnnotationKind.underline


@pytest.mark.anyio
async def test_annotation_editability_follows_author_admin_and_project_owner_rules(async_db):
    db = async_db
    author = User(username="annotation-author", password_hash="unused")
    administrator = User(
        username="annotation-admin",
        password_hash="unused",
        role=SystemRole.administrator,
    )
    owner = User(username="annotation-project-owner", password_hash="unused")
    member = User(username="annotation-project-member", password_hash="unused")
    db.add_all([author, administrator, owner, member])
    await db.flush()
    project = Project(name="Annotation permissions", created_by=owner.id)
    db.add(project)
    await db.flush()
    db.add_all([
        ProjectMember(project_id=project.id, user_id=owner.id, role=ProjectRole.owner),
        ProjectMember(project_id=project.id, user_id=member.id, role=ProjectRole.editor),
    ])
    project_annotation = PdfAnnotation(
        file_revision_id="revision",
        page_index=0,
        author_id=author.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.project,
        project_id=project.id,
        payload={
            "type": "note",
            "rect": {"x": 1, "y": 2, "width": 24, "height": 24},
            "style": {},
        },
    )
    private_annotation = PdfAnnotation(
        file_revision_id="revision",
        page_index=0,
        author_id=author.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.private,
        payload={
            "type": "note",
            "rect": {"x": 1, "y": 2, "width": 24, "height": 24},
            "style": {},
        },
    )

    assert await can_edit_annotation(db, author, project_annotation) is True
    assert await can_edit_annotation(db, administrator, project_annotation) is True
    assert await can_edit_annotation(db, owner, project_annotation) is True
    assert await can_edit_annotation(db, member, project_annotation) is False
    assert await can_edit_annotation(db, owner, private_annotation) is False

    replies = [
        PdfAnnotationReply(
            id="00000000-0000-4000-8000-000000000021",
            annotation_id=project_annotation.id,
            author_id=member.id,
            body="Member",
        ),
        PdfAnnotationReply(
            id="00000000-0000-4000-8000-000000000022",
            annotation_id=project_annotation.id,
            author_id=author.id,
            body="Author",
        ),
    ]
    parents = {project_annotation.id: project_annotation}
    assert await editable_annotation_reply_ids(db, member, replies, parents) == {replies[0].id}
    assert await editable_annotation_reply_ids(db, owner, replies, parents) == {
        reply.id for reply in replies
    }
    assert await editable_annotation_reply_ids(db, administrator, replies, parents) == {
        reply.id for reply in replies
    }


@pytest.mark.anyio
async def test_annotation_update_recomputes_editability_after_scope_or_project_changes(async_db):
    db = async_db
    author = User(username="scope-change-author", password_hash="unused")
    owner = User(username="scope-change-owner", password_hash="unused")
    db.add_all([author, owner])
    await db.flush()
    item = Item(title="Scope change", created_by=author.id)
    source_project = Project(name="Owned source project", created_by=owner.id)
    target_project = Project(name="Editable target project", created_by=author.id)
    db.add_all([item, source_project, target_project])
    await db.flush()
    revision = FileRevision(
        item_id=item.id,
        object_key="scope-change.pdf",
        size=1,
        original_name="scope-change.pdf",
        page_count=1,
        page_geometry="[[0, 0, 100, 100]]",
        processing_state=FileRevisionProcessingState.ready,
        created_by=author.id,
    )
    db.add_all([
        revision,
        ProjectItem(project_id=source_project.id, item_id=item.id),
        ProjectItem(project_id=target_project.id, item_id=item.id),
        ProjectMember(project_id=source_project.id, user_id=owner.id, role=ProjectRole.owner),
        ProjectMember(project_id=target_project.id, user_id=owner.id, role=ProjectRole.editor),
    ])
    await db.flush()
    payload = {
        "type": "note",
        "rect": {"x": 1, "y": 2, "width": 24, "height": 24},
    }
    annotations = [
        PdfAnnotation(
            file_revision_id=revision.id,
            page_index=0,
            author_id=author.id,
            kind=AnnotationKind.note,
            scope=AnnotationScope.project,
            project_id=source_project.id,
            payload=payload,
        )
        for _ in range(2)
    ]
    db.add_all(annotations)
    await db.commit()

    moved_private = await update_document_annotation(
        db,
        owner,
        item.id,
        annotations[0].id,
        AnnotationUpdate(
            version=1,
            page_index=0,
            kind=AnnotationKind.note,
            scope=AnnotationScope.private,
            payload=payload,
        ),
    )
    moved_project = await update_document_annotation(
        db,
        owner,
        item.id,
        annotations[1].id,
        AnnotationUpdate(
            version=1,
            page_index=0,
            kind=AnnotationKind.note,
            scope=AnnotationScope.project,
            project_id=target_project.id,
            payload=payload,
        ),
    )

    assert moved_private["editable"] is False
    assert moved_project["editable"] is False


@pytest.mark.parametrize(
    ("kind", "geometry"),
    [
        ("highlight", {"segment_rects": [{"x": 5, "y": 10, "width": 10, "height": 10}]}),
        ("ink", {"paths": [[{"x": 10, "y": 10}, {"x": 31, "y": 20}]]}),
        ("line", {"start": {"x": 9, "y": 10}, "end": {"x": 30, "y": 30}}),
        ("arrow", {"start": {"x": 10, "y": 10}, "end": {"x": 30, "y": 31}}),
    ],
)
def test_annotation_payload_child_geometry_must_be_enclosed_by_its_rect(kind, geometry):
    revision = FileRevision(
        item_id="item",
        object_key="geometry.pdf",
        size=1,
        original_name="geometry.pdf",
        page_count=1,
        page_geometry="[[0, 0, 100, 100]]",
        processing_state=FileRevisionProcessingState.ready,
        created_by="user",
    )
    data = AnnotationCreate.model_validate({
        "id": "00000000-0000-4000-8000-000000000001",
        "revision_id": "revision",
        "page_index": 0,
        "kind": kind,
        "payload": {
            "type": kind,
            "rect": {"x": 10, "y": 10, "width": 20, "height": 20},
            **geometry,
        },
    })

    with pytest.raises(ValidationFailure, match="enclosing rectangle"):
        validate_payload(data.page_index, data.payload, revision)


@pytest.mark.anyio
async def test_annotation_views_batch_project_owner_editability_queries(async_db):
    db = async_db
    author = User(username="batch-annotation-author", password_hash="unused")
    owner = User(username="batch-annotation-owner", password_hash="unused")
    db.add_all([author, owner])
    await db.flush()
    projects = [
        Project(name=f"Batch annotation project {index}", created_by=owner.id) for index in range(3)
    ]
    db.add_all(projects)
    await db.flush()
    db.add_all([
        ProjectMember(project_id=project.id, user_id=owner.id, role=ProjectRole.owner)
        for project in projects
    ])
    await db.commit()
    db.expunge_all()

    records = [
        PdfAnnotation(
            id=f"00000000-0000-4000-8000-00000000001{index}",
            file_revision_id="revision",
            page_index=0,
            author_id=author.id,
            kind=AnnotationKind.note,
            scope=AnnotationScope.project,
            project_id=project.id,
            payload={
                "type": "note",
                "rect": {"x": 1, "y": 2, "width": 24, "height": 24},
                "style": {},
            },
            version=1,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        for index, project in enumerate(projects)
    ]
    statements = []

    def capture_project_member_queries(_conn, _cursor, statement, *_args):
        if "FROM project_members" in statement:
            statements.append(statement)

    sync_engine = db.bind.sync_engine
    event.listen(sync_engine, "before_cursor_execute", capture_project_member_queries)
    try:
        views = await _annotation_views(db, owner, records)
    finally:
        event.remove(sync_engine, "before_cursor_execute", capture_project_member_queries)

    assert all(view["editable"] for view in views)
    assert len(statements) == 1


def test_annotation_commands_use_domain_types():
    command = AnnotationCreate(
        id="9de91fd4-96eb-4f26-98df-eefbe8a03d67",
        revision_id="revision",
        page_index=0,
        kind="note",
        scope="private",
        payload={"type": "note", "rect": {"x": 1, "y": 2, "width": 24, "height": 24}},
    )

    assert command.kind is AnnotationKind.note
    assert command.scope is AnnotationScope.private


@pytest.mark.anyio
async def test_project_membership_preserves_an_owner_and_returns_domain_roles(async_db):
    db = async_db
    owner = User(username="project-owner", password_hash="unused")
    teammate = User(username="project-teammate", password_hash="unused")
    db.add_all([owner, teammate])
    await db.commit()
    project = await create_project(db, owner, "Lifecycle project")

    with pytest.raises(ProjectMemberConflict, match="retain an owner"):
        await remove_project_member(db, owner, project.id, owner.id)

    added = await add_project_member(db, owner, project.id, teammate.username, ProjectRole.editor)
    assert added.role == ProjectRole.editor
    assert [
        (member.user.username, member.role)
        for member in (await open_project_workspace(db, owner, project.id)).members
    ] == [
        (owner.username, ProjectRole.owner),
        (teammate.username, ProjectRole.editor),
    ]

    await remove_project_member(db, owner, project.id, teammate.id)
    assert [
        (member.user.username, member.role)
        for member in (await open_project_workspace(db, owner, project.id)).members
    ] == [(owner.username, ProjectRole.owner)]
    event = await db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "project.member.remove", AuditEvent.target_id == project.id
        )
    )
    assert event is not None
    assert json.loads(event.detail) == {"user_id": teammate.id}


async def assert_closed_state_constraints(db) -> None:
    member, revision, annotation, project = await state_records(db)
    member_key = {"project_id": member.project_id, "user_id": member.user_id}
    revision_id = revision.id
    annotation_id = annotation.id
    project_id = project.id

    await assert_rejected(
        db,
        "UPDATE project_members SET role = :value WHERE project_id = :project_id AND user_id = :user_id",
        {"value": "guest", **member_key},
    )
    await assert_rejected(
        db,
        "UPDATE file_revisions SET processing_state = :value WHERE id = :id",
        {"value": "unknown", "id": revision_id},
    )
    await assert_rejected(
        db,
        "UPDATE pdf_annotations SET kind = :value WHERE id = :id",
        {"value": "drawing", "id": annotation_id},
    )
    await assert_rejected(
        db,
        "UPDATE pdf_annotations SET scope = :scope WHERE id = :id",
        {"scope": "public", "id": annotation_id},
    )
    await assert_rejected(
        db,
        "UPDATE pdf_annotations SET scope = 'project', project_id = NULL WHERE id = :id",
        {"id": annotation_id},
    )
    await assert_rejected(
        db,
        "UPDATE pdf_annotations SET scope = 'private', project_id = :project_id WHERE id = :id",
        {"project_id": project_id, "id": annotation_id},
    )


@pytest.mark.anyio
async def test_database_rejects_invalid_closed_states_and_scope_combinations(async_db):
    await assert_closed_state_constraints(async_db)
