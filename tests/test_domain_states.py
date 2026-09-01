from __future__ import annotations

import json

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from quirebase.core.errors import ValidationFailure
from quirebase.documents.schemas import AnnotationCreate, SegmentInput
from quirebase.models import (
    AnnotationKind,
    AnnotationScope,
    AuditEvent,
    FileRevision,
    FileRevisionProcessingState,
    Item,
    Job,
    JobState,
    PdfAnnotation,
    Project,
    ProjectMember,
    ProjectRole,
    User,
)
from quirebase.pipeline.jobs import enqueue_job
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
        sha256="0" * 64,
        size=1,
        original_name="state.pdf",
        created_by=user.id,
    )
    db.add_all([member, revision])
    await db.flush()
    annotation = PdfAnnotation(
        file_revision_id=revision.id,
        author_id=user.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.private,
    )
    job = Job(kind="pdf.inspect", payload="{}", idempotency_key="state:1")
    db.add_all([annotation, job])
    await db.commit()
    return member, revision, annotation, job, project


async def assert_rejected(db, statement: str, parameters: dict[str, str]) -> None:
    with pytest.raises(IntegrityError):
        await db.execute(text(statement), parameters)
    await db.rollback()


@pytest.mark.anyio
async def test_closed_domain_states_are_loaded_as_domain_types(async_db):
    db = async_db
    member, revision, annotation, job, _project = await state_records(db)
    keys = (member.project_id, member.user_id, revision.id, annotation.id, job.id)

    db.expunge_all()

    loaded_member = await db.get(ProjectMember, keys[:2])
    loaded_revision = await db.get(FileRevision, keys[2])
    loaded_annotation = await db.get(PdfAnnotation, keys[3])
    loaded_job = await db.get(Job, keys[4])
    assert loaded_member is not None and loaded_member.role is ProjectRole.owner
    assert loaded_revision is not None
    assert loaded_revision.processing_state is FileRevisionProcessingState.pending
    assert loaded_annotation is not None and loaded_annotation.kind is AnnotationKind.note
    assert loaded_annotation.scope is AnnotationScope.private
    assert loaded_job is not None and loaded_job.state is JobState.pending


@pytest.mark.anyio
async def test_underline_is_an_allowed_annotation_kind(async_db):
    db = async_db
    _member, _revision, annotation, _job, _project = await state_records(db)
    annotation_id = annotation.id

    await db.execute(
        text("UPDATE pdf_annotations SET kind = 'underline' WHERE id = :id"),
        {"id": annotation.id},
    )
    await db.commit()
    db.expunge_all()

    loaded = await db.get(PdfAnnotation, annotation_id)
    assert loaded is not None and loaded.kind is AnnotationKind.underline


def test_annotation_commands_use_domain_types():
    command = AnnotationCreate(
        revision_id="revision",
        kind="note",
        scope="private",
        segments=[SegmentInput(page_index=0, anchor_x=1, anchor_y=2)],
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
    member, revision, annotation, job, project = await state_records(db)
    member_key = {"project_id": member.project_id, "user_id": member.user_id}
    revision_id = revision.id
    annotation_id = annotation.id
    job_id = job.id
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
    await assert_rejected(
        db,
        "UPDATE jobs SET kind = '' WHERE id = :id",
        {"id": job_id},
    )
    await assert_rejected(
        db,
        "UPDATE jobs SET state = :value WHERE id = :id",
        {"value": "cancelled", "id": job_id},
    )


@pytest.mark.anyio
async def test_database_rejects_invalid_closed_states_and_scope_combinations(async_db):
    await assert_closed_state_constraints(async_db)


@pytest.mark.anyio
async def test_enqueue_job_accepts_extensible_kinds_but_rejects_invalid_shape(async_db):
    db = async_db
    job = await enqueue_job(db, "custom.not_registered", json.loads("{}"))
    assert job.kind == "custom.not_registered"

    with pytest.raises(ValidationFailure, match="1 to 40"):
        await enqueue_job(db, " ", {})
