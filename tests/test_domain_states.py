from __future__ import annotations

import json

import pytest
from sqlalchemy import text
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


def state_records(db):
    user = User(username="state-owner", password_hash="unused")
    db.add(user)
    db.flush()
    item = Item(title="State constraints", created_by=user.id)
    project = Project(name="State project", created_by=user.id)
    db.add_all([item, project])
    db.flush()
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
    db.flush()
    annotation = PdfAnnotation(
        file_revision_id=revision.id,
        author_id=user.id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.private,
    )
    job = Job(kind="pdf.inspect", payload="{}", idempotency_key="state:1")
    db.add_all([annotation, job])
    db.commit()
    return member, revision, annotation, job, project


def assert_rejected(db, statement: str, parameters: dict[str, str]) -> None:
    with pytest.raises(IntegrityError), db.begin_nested():
        db.execute(text(statement), parameters)
    db.rollback()


def test_closed_domain_states_are_loaded_as_domain_types(db):
    member, revision, annotation, job, _project = state_records(db)

    db.expire_all()

    assert db.get(ProjectMember, (member.project_id, member.user_id)).role is ProjectRole.owner
    assert db.get(FileRevision, revision.id).processing_state is FileRevisionProcessingState.pending
    assert db.get(PdfAnnotation, annotation.id).kind is AnnotationKind.note
    assert db.get(PdfAnnotation, annotation.id).scope is AnnotationScope.private
    assert db.get(Job, job.id).state is JobState.pending


def test_underline_is_an_allowed_annotation_kind(db):
    _member, _revision, annotation, _job, _project = state_records(db)

    db.execute(
        text("UPDATE pdf_annotations SET kind = 'underline' WHERE id = :id"),
        {"id": annotation.id},
    )
    db.commit()
    db.expire_all()

    assert db.get(PdfAnnotation, annotation.id).kind is AnnotationKind.underline


def test_annotation_commands_use_domain_types():
    command = AnnotationCreate(
        revision_id="revision",
        kind="note",
        scope="private",
        segments=[SegmentInput(page_index=0, anchor_x=1, anchor_y=2)],
    )

    assert command.kind is AnnotationKind.note
    assert command.scope is AnnotationScope.private


def test_project_membership_preserves_an_owner_and_returns_domain_roles(db):
    owner = User(username="project-owner", password_hash="unused")
    teammate = User(username="project-teammate", password_hash="unused")
    db.add_all([owner, teammate])
    db.commit()
    project = create_project(db, owner, "Lifecycle project")

    with pytest.raises(ProjectMemberConflict, match="retain an owner"):
        remove_project_member(db, owner, project.id, owner.id)

    added = add_project_member(db, owner, project.id, teammate.username, ProjectRole.editor)
    assert added.role == ProjectRole.editor
    assert [
        (member.user.username, member.role)
        for member in open_project_workspace(db, owner, project.id).members
    ] == [
        (owner.username, ProjectRole.owner),
        (teammate.username, ProjectRole.editor),
    ]

    remove_project_member(db, owner, project.id, teammate.id)
    assert [
        (member.user.username, member.role)
        for member in open_project_workspace(db, owner, project.id).members
    ] == [(owner.username, ProjectRole.owner)]
    event = (
        db.query(AuditEvent).filter_by(action="project.member.remove", target_id=project.id).one()
    )
    assert json.loads(event.detail) == {"user_id": teammate.id}


def assert_closed_state_constraints(db) -> None:
    member, revision, annotation, job, project = state_records(db)

    assert_rejected(
        db,
        "UPDATE project_members SET role = :value WHERE project_id = :project_id AND user_id = :user_id",
        {"value": "guest", "project_id": member.project_id, "user_id": member.user_id},
    )
    assert_rejected(
        db,
        "UPDATE file_revisions SET processing_state = :value WHERE id = :id",
        {"value": "unknown", "id": revision.id},
    )
    assert_rejected(
        db,
        "UPDATE pdf_annotations SET kind = :value WHERE id = :id",
        {"value": "drawing", "id": annotation.id},
    )
    assert_rejected(
        db,
        "UPDATE pdf_annotations SET scope = :scope WHERE id = :id",
        {"scope": "public", "id": annotation.id},
    )
    assert_rejected(
        db,
        "UPDATE pdf_annotations SET scope = 'project', project_id = NULL WHERE id = :id",
        {"id": annotation.id},
    )
    assert_rejected(
        db,
        "UPDATE pdf_annotations SET scope = 'private', project_id = :project_id WHERE id = :id",
        {"project_id": project.id, "id": annotation.id},
    )
    assert_rejected(
        db,
        "UPDATE jobs SET kind = '' WHERE id = :id",
        {"id": job.id},
    )
    assert_rejected(
        db,
        "UPDATE jobs SET state = :value WHERE id = :id",
        {"value": "cancelled", "id": job.id},
    )


def test_database_rejects_invalid_closed_states_and_scope_combinations(db):
    assert_closed_state_constraints(db)


def test_enqueue_job_accepts_extensible_kinds_but_rejects_invalid_shape(db):
    job = enqueue_job(db, "custom.not_registered", json.loads("{}"))
    assert job.kind == "custom.not_registered"

    with pytest.raises(ValidationFailure, match="1 to 40"):
        enqueue_job(db, " ", {})
