"""Behavior at the owner-operated deletion and governance seams."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from advanced_alchemy.types import FileObject
from import_helpers import pdf_import_batch_data
from sqlalchemy import select, text
from workspace_helpers import provision_initial_workspace

from quirebase.access import resolve_workspace_context
from quirebase.accounts import update_user_status
from quirebase.core.config import get_settings
from quirebase.core.errors import PermissionDenied, ResourceUnavailable
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.core.workflows import object_reservation_attributes
from quirebase.documents import (
    delete_unreferenced_objects,
    list_expired_export_artifacts,
    retire_expired_export_artifacts,
)
from quirebase.library import ItemSection, open_item_section
from quirebase.models import (
    AnnotationKind,
    AnnotationScope,
    Attachment,
    AuditEvent,
    DiscussionMessage,
    ExportArtifact,
    FileRevision,
    ImportBatch,
    Item,
    LoginSession,
    PdfAnnotation,
    PdfAnnotationReply,
    Project,
    ProjectItem,
    ProjectParticipant,
    ProjectParticipation,
    ProjectState,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.operations.maintenance import delete_orphan_candidates, scan_objects
from quirebase.projects import (
    delete_project,
    list_item_organize_projects,
    list_workspace_projects,
    open_project_workspace,
    set_project_state,
)
from quirebase.search import search_index
from quirebase.workspaces import delete_workspace

pytestmark = pytest.mark.shared_postgres


async def _workspace(db):
    user = User(username=f"owner-{uuid4()}", password_hash="unused")
    db.add(user)
    await db.flush()
    workspace = await provision_initial_workspace(db, user)
    await db.commit()
    return user.id, workspace.id


def _file(stored):
    return FileObject(
        backend="documents",
        filename=stored.key,
        size=stored.size,
        content_type="application/pdf",
        metadata={"original_name": "test.pdf"},
    )


def _artifact(stored, workspace_id, *, expired=False):
    return ExportArtifact(
        workflow_id=f"export-{uuid4()}",
        workspace_id=workspace_id,
        expires_at=datetime.now(UTC) + timedelta(hours=-1 if expired else 1),
        file=_file(stored),
    )


@pytest.mark.anyio
@pytest.mark.parametrize("state", [ProjectState.active, ProjectState.archived])
async def test_project_delete_cascades_context_and_preserves_workspace_data(
    persistence_sessions, state
):
    store = get_object_store()
    stored = await store.put_object(uuid4(), ObjectSuffix.PDF, b"preserved PDF", max_bytes=100)
    async with persistence_sessions() as db:
        owner_id, workspace_id = await _workspace(db)
        owner = await db.get(User, owner_id)
        member_id = await db.scalar(
            select(WorkspaceMember.id).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == owner_id,
            )
        )
        project = Project(
            workspace_id=workspace_id, name="Delete context", created_by=owner_id, state=state
        )
        other = Project(workspace_id=workspace_id, name="Preserve context", created_by=owner_id)
        item = Item(
            workspace_id=workspace_id,
            created_by=owner_id,
            work={
                "id": f"urn:uuid:{uuid4()}",
                "type": "Document",
                "title": "Shared canonical Item",
            },
        )
        db.add_all([project, other, item])
        await db.flush()
        assignments = [
            ProjectItem(
                workspace_id=workspace_id, project_id=root.id, item_id=item.id, added_by=owner_id
            )
            for root in (project, other)
        ]
        participants = [
            ProjectParticipant(
                workspace_id=workspace_id,
                project_id=root.id,
                workspace_member_id=member_id,
                user_id=owner_id,
            )
            for root in (project, other)
        ]
        discussions = [
            DiscussionMessage(
                workspace_id=workspace_id,
                project_id=root.id,
                author_id=owner_id,
                body="Project discussion",
            )
            for root in (project, other)
        ]
        item_discussion = DiscussionMessage(
            workspace_id=workspace_id, item_id=item.id, author_id=owner_id, body="Item discussion"
        )
        revision = FileRevision(
            workspace_id=workspace_id, item_id=item.id, created_by=owner_id, file=_file(stored)
        )
        attachment = Attachment(
            workspace_id=workspace_id, item_id=item.id, created_by=owner_id, file=_file(stored)
        )
        db.add_all([
            *assignments,
            *participants,
            *discussions,
            item_discussion,
            revision,
            attachment,
        ])
        await db.flush()
        annotations = [
            PdfAnnotation(
                workspace_id=workspace_id,
                file_revision_id=revision.id,
                item_id=item.id,
                page_index=0,
                author_id=owner_id,
                kind=AnnotationKind.note,
                scope=AnnotationScope.private if assignment is None else AnnotationScope.project,
                project_item_id=None if assignment is None else assignment.id,
                payload={},
            )
            for assignment in (*assignments, None)
        ]
        db.add_all(annotations)
        await db.flush()
        replies = [
            PdfAnnotationReply(
                workspace_id=workspace_id,
                annotation_id=annotation.id,
                author_id=owner_id,
                body="Reply",
            )
            for annotation in annotations
        ]
        db.add_all(replies)
        await db.commit()
        removed = (
            project,
            assignments[0],
            participants[0],
            discussions[0],
            annotations[0],
            replies[0],
        )
        preserved = (
            other,
            item,
            revision,
            attachment,
            item_discussion,
            assignments[1],
            participants[1],
            discussions[1],
            *annotations[1:],
            *replies[1:],
        )
        removed_ids = [(type(row), row.id) for row in removed]
        preserved_ids = [(type(row), row.id) for row in preserved]
        project_id, name = project.id, project.name
        await delete_project(db, owner, workspace_id, project_id)

    async with persistence_sessions() as db:
        for model, identity in removed_ids:
            assert await db.get(model, identity) is None
        for model, identity in preserved_ids:
            assert await db.get(model, identity) is not None
        assert await db.get(Workspace, workspace_id) is not None
        audit = await db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "project.delete", AuditEvent.project_id == project_id
            )
        )
        assert audit is not None
        assert audit.target_id == str(project_id)
        assert audit.workspace_id == workspace_id
        assert audit.detail == {"name": name}
        assert audit.authorization_resource_action == "project.delete"
        owner = await db.get(User, owner_id)
        with pytest.raises(ResourceUnavailable):
            await set_project_state(db, owner, workspace_id, project_id, ProjectState.active)
        with pytest.raises(ResourceUnavailable):
            await delete_project(db, owner, workspace_id, project_id)
    assert await store.exists(stored.key)


@pytest.mark.anyio
@pytest.mark.parametrize("guard", ["authority", "rollback"])
async def test_project_delete_guards_and_rollback_preserve_context(
    persistence_sessions, monkeypatch, guard
):
    async with persistence_sessions() as db:
        owner_id, workspace_id = await _workspace(db)
        owner = await db.get(User, owner_id)
        editor = User(username=f"editor-{uuid4()}", password_hash="unused")
        db.add(editor)
        await db.flush()
        db.add(
            WorkspaceMember(workspace_id=workspace_id, user_id=editor.id, role=WorkspaceRole.editor)
        )
        project = Project(workspace_id=workspace_id, name="Guarded context", created_by=owner_id)
        item = Item(
            workspace_id=workspace_id,
            created_by=owner_id,
            work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Guarded Item"},
        )
        db.add_all([project, item])
        await db.flush()
        assignment = ProjectItem(
            workspace_id=workspace_id, project_id=project.id, item_id=item.id, added_by=owner_id
        )
        db.add(assignment)
        await db.commit()
        project_id, assignment_id = project.id, assignment.id
        if guard == "rollback":

            async def fail_commit():
                assert await db.scalar(select(Project.id).where(Project.id == project_id)) is None
                assert (
                    await db.scalar(select(ProjectItem.id).where(ProjectItem.id == assignment_id))
                    is None
                )
                raise RuntimeError("commit aborted")

            monkeypatch.setattr(db, "commit", fail_commit)
        error = {
            "authority": PermissionDenied,
            "rollback": RuntimeError,
        }[guard]
        with pytest.raises(error):
            await delete_project(
                db,
                editor if guard == "authority" else owner,
                workspace_id,
                project_id,
            )
        await db.rollback()
    async with persistence_sessions() as db:
        project = await db.get(Project, project_id)
        assert project is not None and project.state is ProjectState.active
        assert await db.get(ProjectItem, assignment_id) is not None
        assert (
            await db.scalar(
                select(AuditEvent.id).where(
                    AuditEvent.action == "project.delete", AuditEvent.project_id == project_id
                )
            )
            is None
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "reference",
    ["revision", "thumbnail", "attachment", "export", "pending", "ready", "failed", "committed"],
)
async def test_final_cleanup_rechecks_references_added_after_scan(persistence_sessions, reference):
    store = get_object_store()
    stored = await store.put_object(uuid4(), ObjectSuffix.PDF, b"late-reference", max_bytes=100)
    old = (datetime.now(UTC) - timedelta(hours=2)).timestamp()
    os.utime(get_settings().object_dir / stored.key, (old, old))
    async with persistence_sessions() as db:
        owner_id, workspace_id = await _workspace(db)
        _, candidates, _ = await scan_objects(db, retention_hours=1)
        assert stored.key in candidates
    async with persistence_sessions() as writer:
        item = Item(
            workspace_id=workspace_id,
            created_by=owner_id,
            work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Late reference"},
        )
        writer.add(item)
        await writer.flush()
        if reference in {"revision", "thumbnail"}:
            other = await store.put_object(uuid4(), ObjectSuffix.PDF, b"source", max_bytes=100)
            writer.add(
                FileRevision(
                    workspace_id=workspace_id,
                    item_id=item.id,
                    created_by=owner_id,
                    file=_file(stored if reference == "revision" else other),
                    thumbnail=_file(stored) if reference == "thumbnail" else None,
                )
            )
        elif reference == "attachment":
            writer.add(
                Attachment(
                    workspace_id=workspace_id,
                    item_id=item.id,
                    created_by=owner_id,
                    file=_file(stored),
                )
            )
        elif reference == "export":
            writer.add(_artifact(stored, workspace_id))
        else:
            writer.add(
                ImportBatch(
                    workspace_id=workspace_id,
                    actor_id=owner_id,
                    file_format="pdf",
                    status=reference,
                    errors=[],
                    **pdf_import_batch_data([{"_pdf": {"object_key": stored.key}}]),
                )
            )
        await writer.commit()
    async with persistence_sessions() as cleaner:
        expected = (stored.key,) if reference == "committed" else ()
        assert await delete_orphan_candidates(cleaner, candidates) == expected
        assert await store.exists(stored.key) is (reference != "committed")
        assert await delete_orphan_candidates(cleaner, candidates) == ()


@pytest.mark.anyio
async def test_cleanup_sees_finalizer_committed_during_reservation_read(
    persistence_sessions, monkeypatch
):
    store = get_object_store()
    stored = await store.put_object(uuid4(), ObjectSuffix.PDF, b"finalized", max_bytes=100)
    async with persistence_sessions() as db:
        _, workspace_id = await _workspace(db)

    async def finalizer_completes(**kwargs):
        async with persistence_sessions() as writer:
            writer.add(_artifact(stored, workspace_id))
            await writer.commit()
        # Its execution has become terminal and no longer appears in the active list.
        return set()

    monkeypatch.setattr(
        "quirebase.documents.objects.active_object_reservations", finalizer_completes
    )
    async with persistence_sessions() as db:
        assert await delete_unreferenced_objects(db, [stored.key]) == ()
    assert await store.exists(stored.key)


@pytest.mark.anyio
async def test_cleanup_rechecks_later_keys_after_prior_delete_io(persistence_sessions, monkeypatch):
    store = get_object_store()
    first = await store.put_object(uuid4(), ObjectSuffix.PDF, b"first", max_bytes=100)
    later = await store.put_object(uuid4(), ObjectSuffix.PDF, b"later", max_bytes=100)
    async with persistence_sessions() as db:
        _, workspace_id = await _workspace(db)

    class Store:
        async def delete(self, key):
            if key == first.key:
                async with persistence_sessions() as writer:
                    writer.add(_artifact(later, workspace_id))
                    await writer.commit()
            return await store.delete(key)

    monkeypatch.setattr("quirebase.documents.objects.get_object_store", Store)
    async with persistence_sessions() as db:
        assert await delete_unreferenced_objects(db, [first.key, later.key]) == (first.key,)
    assert await store.exists(later.key)


@pytest.mark.anyio
async def test_cleanup_preserves_atomic_import_staging_to_revision_transfer(
    persistence_sessions, monkeypatch
):
    from quirebase.documents import objects

    store = get_object_store()
    stored = await store.put_object(uuid4(), ObjectSuffix.PDF, b"confirmed", max_bytes=100)
    async with persistence_sessions() as db:
        owner_id, workspace_id = await _workspace(db)
        batch = ImportBatch(
            workspace_id=workspace_id,
            actor_id=owner_id,
            file_format="pdf",
            status="ready",
            errors=[],
            **pdf_import_batch_data([{"_pdf": {"object_key": stored.key}}]),
        )
        db.add(batch)
        await db.commit()
        batch_id = batch.id
    original_read = objects._document_object_keys

    async def confirm_after_document_read(db, *args, **kwargs):
        observed = await original_read(db, *args, **kwargs)
        async with persistence_sessions() as writer:
            batch = await writer.get(ImportBatch, batch_id)
            item = Item(
                workspace_id=workspace_id,
                created_by=owner_id,
                work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Confirmed"},
            )
            writer.add(item)
            await writer.flush()
            writer.add(
                FileRevision(
                    workspace_id=workspace_id,
                    item_id=item.id,
                    created_by=owner_id,
                    file=_file(stored),
                )
            )
            batch.staged_files = []
            batch.status = "committed"
            await writer.commit()
        return observed

    monkeypatch.setattr(objects, "_document_object_keys", confirm_after_document_read)
    async with persistence_sessions() as db:
        assert await delete_unreferenced_objects(db, [stored.key]) == ()
    assert await store.exists(stored.key)


@pytest.mark.anyio
async def test_cleanup_intent_and_own_workflow_exclusion_do_not_hide_other_owners(
    async_db, fake_durable_operations
):
    store = get_object_store()
    stored = await store.put_object(uuid4(), ObjectSuffix.PDF, b"reserved", max_bytes=100)
    for identity, intent in [("own", "reserve"), ("other", "reserve"), ("teardown", "cleanup")]:
        await fake_durable_operations.enqueue(
            "any-workflow",
            queue_name="test",
            workflow_id=identity,
            attributes=object_reservation_attributes([stored.key], intent=intent),
        )
    assert await delete_unreferenced_objects(async_db, [stored.key], ignore_workflow_id="own") == ()
    fake_durable_operations.workflows["other"] = replace(
        fake_durable_operations.workflows["other"], state="succeeded"
    )
    assert await delete_unreferenced_objects(async_db, [stored.key], ignore_workflow_id="own") == (
        stored.key,
    )
    assert await delete_unreferenced_objects(async_db, [stored.key], ignore_workflow_id="own") == ()


@pytest.mark.anyio
async def test_expiration_releases_matching_descriptors_then_recovers_failed_io(
    persistence_sessions, monkeypatch
):
    store = get_object_store()
    stored = await store.put_object(uuid4(), ObjectSuffix.PDF, b"expire", max_bytes=100)
    async with persistence_sessions() as db:
        _, workspace_id = await _workspace(db)
        artifact = _artifact(stored, workspace_id, expired=True)
        db.add(artifact)
        await db.commit()
        receipt = await list_expired_export_artifacts(db, 100)
        # Release and its keys form one durable datasource checkpoint.
        keys = await retire_expired_export_artifacts(db, receipt)
        await db.commit()
        assert await db.get(ExportArtifact, artifact.workflow_id) is None
        assert keys == (stored.key,)

    class FailedStore:
        async def delete(self, key):
            raise OSError("object store unavailable")

    monkeypatch.setattr("quirebase.documents.objects.get_object_store", FailedStore)
    async with persistence_sessions() as db:
        with pytest.raises(OSError):
            await delete_unreferenced_objects(db, keys)
    monkeypatch.setattr("quirebase.documents.objects.get_object_store", lambda: store)
    async with persistence_sessions() as db:
        assert await delete_unreferenced_objects(db, keys) == keys
        assert await delete_unreferenced_objects(db, keys) == ()


@pytest.mark.anyio
async def test_expiration_rechecks_lifetime_and_preserves_other_references(persistence_sessions):
    store = get_object_store()
    stored = await store.put_object(uuid4(), ObjectSuffix.PDF, b"shared", max_bytes=100)
    async with persistence_sessions() as db:
        _, workspace_id = await _workspace(db)
        expired, renewed, live = (
            _artifact(stored, workspace_id, expired=True),
            _artifact(stored, workspace_id, expired=True),
            _artifact(stored, workspace_id),
        )
        db.add_all([expired, renewed, live])
        await db.commit()
        receipts = await list_expired_export_artifacts(db, 100)
        renewed.expires_at = datetime.now(UTC) + timedelta(days=1)
        await db.commit()
        keys = await retire_expired_export_artifacts(db, receipts)
        await db.commit()
        renewed_id, live_id = renewed.workflow_id, live.workflow_id
        assert await delete_unreferenced_objects(db, keys) == ()
        assert await db.get(ExportArtifact, renewed_id) is not None
        assert await db.get(ExportArtifact, live_id) is not None
    assert await store.exists(stored.key)


@pytest.mark.anyio
async def test_dbos_expiration_retries_io_and_replays_retirement_checkpoint(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    from dbos import DBOS, DBOSConfig, SetWorkflowID

    from quirebase.operations import workflows as maintenance

    store = get_object_store()
    stored = await store.put_object(uuid4(), ObjectSuffix.PDF, b"checkpoint", max_bytes=100)
    _, workspace_id = await _workspace(async_db)
    artifact = _artifact(stored, workspace_id, expired=True)
    async_db.add(artifact)
    await async_db.commit()
    artifact_id = artifact.workflow_id
    receipts = await list_expired_export_artifacts(async_db, 100)
    await async_db.rollback()
    retire_calls = 0
    delete_attempts = 0
    original_retire = maintenance.retire_expired_export_artifacts

    async def retire(db, values):
        nonlocal retire_calls
        retire_calls += 1
        return await original_retire(db, values)

    class TransientStore:
        async def delete(self, key):
            nonlocal delete_attempts
            delete_attempts += 1
            async with async_session_factory() as fresh:
                assert await fresh.get(ExportArtifact, artifact_id) is None
            if delete_attempts == 1:
                raise OSError("transient object-store error")
            return await store.delete(key)

    monkeypatch.setattr(maintenance, "retire_expired_export_artifacts", retire)
    monkeypatch.setattr(maintenance, "AsyncSessionLocal", async_session_factory)
    monkeypatch.setattr("quirebase.documents.objects.get_object_store", TransientStore)
    DBOS(
        config=DBOSConfig(
            name="expiry-recovery", system_database_url=f"sqlite:///{tmp_path / 'expiry-system.db'}"
        )
    )
    DBOS.launch()

    @DBOS.workflow()
    async def expire_with_checkpoint(values):
        keys = await maintenance.retire_expired_export_artifacts_step(values)
        return await maintenance.delete_export_artifact_objects_step(keys)

    try:
        identity = f"expire-test-{uuid4()}"
        with SetWorkflowID(identity):
            assert await expire_with_checkpoint(receipts) == 1
        with SetWorkflowID(identity):
            assert await expire_with_checkpoint(receipts) == 1
        assert retire_calls == 1 and delete_attempts == 2
        checkpoints = await async_db.execute(
            text("SELECT step_id FROM datasource_outputs WHERE workflow_id = :identity"),
            {"identity": identity},
        )
        assert len(checkpoints.all()) == 1
        assert not await store.exists(stored.key)
    finally:
        DBOS.destroy()


@pytest.mark.anyio
@pytest.mark.parametrize("archived", [False, True])
async def test_owner_deactivation_preserves_ownership_and_revokes_session(
    persistence_sessions, archived
):
    async with persistence_sessions() as db:
        owner_id, workspace_id = await _workspace(db)
        owner = await db.get(User, owner_id)
        admin = User(username=f"admin-{uuid4()}", password_hash="unused", role="administrator")
        db.add(admin)
        if archived:
            workspace = await db.get(Workspace, workspace_id)
            workspace.state = WorkspaceState.archived
            workspace.archived_at = datetime.now(UTC)
        session = LoginSession(
            user_id=owner_id,
            token_hash=uuid4().hex,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        db.add(session)
        await db.commit()
        session_id = session.id
        await update_user_status(db, admin, owner_id, False)
        assert not owner.active
        assert await db.get(LoginSession, session_id) is None
        assert (
            await db.scalar(
                select(WorkspaceMember.user_id).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == WorkspaceRole.owner,
                    WorkspaceMember.terminated_at.is_(None),
                )
            )
            == owner_id
        )
        assert (
            await db.scalar(
                select(AuditEvent.id).where(AuditEvent.action == "admin.user.status_update")
            )
            is not None
        )


@pytest.mark.anyio
async def test_non_owner_deactivation_owns_status_session_revocation_and_commit(
    persistence_sessions,
):
    async with persistence_sessions() as db:
        _, workspace_id = await _workspace(db)
        admin = User(username=f"admin-{uuid4()}", password_hash="unused", role="administrator")
        target = User(username=f"target-{uuid4()}", password_hash="unused")
        db.add_all([admin, target])
        await db.flush()
        db.add(
            WorkspaceMember(workspace_id=workspace_id, user_id=target.id, role=WorkspaceRole.admin)
        )
        session = LoginSession(
            user_id=target.id,
            token_hash=uuid4().hex,
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        db.add(session)
        await db.commit()
        target_id, session_id = target.id, session.id
        await update_user_status(db, admin, target_id, False)
    async with persistence_sessions() as fresh:
        assert not (await fresh.get(User, target_id)).active
        assert await fresh.get(LoginSession, session_id) is None
        audit = await fresh.scalar(
            select(AuditEvent).where(AuditEvent.action == "admin.user.status_update")
        )
        assert audit.target_id == str(target_id)
        assert audit.detail["active"] is False


@pytest.mark.anyio
async def test_organize_uses_complete_active_options_and_projects_participation(
    persistence_sessions,
):
    async with persistence_sessions() as db:
        owner_id, workspace_id = await _workspace(db)
        owner = await db.get(User, owner_id)
        item = Item(
            workspace_id=workspace_id,
            created_by=owner_id,
            work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Options"},
        )
        db.add(item)
        implicit = [
            Project(
                workspace_id=workspace_id,
                name=f"Implicit {index:02d}",
                created_by=owner_id,
                participation=ProjectParticipation.workspace,
            )
            for index in range(30)
        ]
        open_project = Project(
            workspace_id=workspace_id,
            name="Open",
            created_by=owner_id,
            participation=ProjectParticipation.open,
        )
        managed = Project(
            workspace_id=workspace_id,
            name="Managed",
            created_by=owner_id,
            participation=ProjectParticipation.managed,
        )
        archived = Project(
            workspace_id=workspace_id,
            name="Archived",
            created_by=owner_id,
            participation=ProjectParticipation.workspace,
            state=ProjectState.archived,
        )
        deleted = Project(
            workspace_id=workspace_id,
            name="Deleted",
            created_by=owner_id,
            participation=ProjectParticipation.workspace,
        )
        db.add_all([*implicit, open_project, managed, archived, deleted])
        await db.commit()
        await delete_project(db, owner, workspace_id, deleted.id)
        context = await resolve_workspace_context(db, owner, workspace_id)
        options = await list_item_organize_projects(db, context)
        assert len(options) == 32
        assert {project.id for project, _ in options} == {
            project.id for project in [*implicit, open_project, managed]
        }
        assert all(participating for project, participating in options if project in implicit)
        assert not {project.id: participating for project, participating in options}[managed.id]
        directory, total = await list_workspace_projects(db, context)
        assert len(directory) == 25 and total == 33
        section = await open_item_section(db, context, item.id, ItemSection.organize)
        assert (
            tuple((option.project, option.is_participating) for option in section.projects)
            == options
        )
        assert (await open_project_workspace(db, context, managed.id)).is_participating is False


@pytest.mark.anyio
async def test_organize_participation_tracks_membership_generation_and_discovery(
    persistence_sessions,
):
    async with persistence_sessions() as db:
        owner_id, workspace_id = await _workspace(db)
        target = User(username=f"participant-{uuid4()}", password_hash="unused")
        db.add(target)
        await db.flush()
        member = WorkspaceMember(
            workspace_id=workspace_id, user_id=target.id, role=WorkspaceRole.editor
        )
        open_project = Project(
            workspace_id=workspace_id,
            name="Open",
            created_by=owner_id,
            participation=ProjectParticipation.open,
        )
        managed = Project(
            workspace_id=workspace_id,
            name="Managed",
            created_by=owner_id,
            participation=ProjectParticipation.managed,
        )
        db.add_all([member, open_project, managed])
        await db.flush()
        selections = [
            ProjectParticipant(
                workspace_id=workspace_id,
                project_id=project.id,
                workspace_member_id=member.id,
                user_id=target.id,
            )
            for project in (open_project, managed)
        ]
        db.add_all(selections)
        await db.commit()
        context = await resolve_workspace_context(db, target, workspace_id)
        assert all(
            participating for _, participating in await list_item_organize_projects(db, context)
        )
        member.state = WorkspaceMemberState.suspended
        await db.commit()
        from quirebase.core.errors import WorkspaceMembershipRequired

        with pytest.raises(WorkspaceMembershipRequired):
            await resolve_workspace_context(db, target, workspace_id)
        member.state = WorkspaceMemberState.active
        await db.commit()
        context = await resolve_workspace_context(db, target, workspace_id)
        assert all(
            participating for _, participating in await list_item_organize_projects(db, context)
        )
        # Simulate a retained selection from a prior generation: it grants neither
        # participation nor managed discovery to the fresh membership.
        member.terminated_at = datetime.now(UTC)
        await db.flush()
        db.add(
            WorkspaceMember(workspace_id=workspace_id, user_id=target.id, role=WorkspaceRole.editor)
        )
        await db.commit()
        context = await resolve_workspace_context(db, target, workspace_id)
        options = await list_item_organize_projects(db, context)
        assert [(project.id, participating) for project, participating in options] == [
            (open_project.id, False)
        ]


@pytest.mark.anyio
async def test_workspace_teardown_cleans_owned_projections_and_rollback_is_atomic(
    persistence_sessions, fake_durable_operations, monkeypatch
):
    async with persistence_sessions() as db:
        owner_id, workspace_id = await _workspace(db)
        owner = await db.get(User, owner_id)
        item = Item(
            workspace_id=workspace_id,
            created_by=owner_id,
            work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Teardown searchable"},
        )
        db.add(item)
        await db.flush()
        stored = await get_object_store().put_object(
            uuid4(), ObjectSuffix.PDF, b"source", max_bytes=100
        )
        revision = FileRevision(
            workspace_id=workspace_id,
            item_id=item.id,
            created_by=owner_id,
            file=_file(stored),
            full_text="Teardown text",
        )
        db.add(revision)
        await db.flush()
        annotation = PdfAnnotation(
            workspace_id=workspace_id,
            file_revision_id=revision.id,
            item_id=item.id,
            page_index=0,
            author_id=owner_id,
            kind="note",
            scope="private",
            payload={},
        )
        db.add(annotation)
        await db.flush()
        reply = PdfAnnotationReply(
            workspace_id=workspace_id, annotation_id=annotation.id, author_id=owner_id, body="Reply"
        )
        db.add(reply)
        await search_index(db).index_item(db, item.id)
        await search_index(db).index_revision(db, revision.id)
        workspace = await db.get(Workspace, workspace_id)
        workspace.state = WorkspaceState.archived
        workspace.archived_at = datetime.now(UTC) - timedelta(days=3650)
        await db.commit()
        identities, item_id = (annotation.id, reply.id), item.id

        original_enqueue = fake_durable_operations.enqueue_in_transaction

        async def fail_enqueue(*args, **kwargs):
            await asyncio.sleep(0)
            raise RuntimeError("durable enqueue unavailable")

        monkeypatch.setattr(fake_durable_operations, "enqueue_in_transaction", fail_enqueue)
        with pytest.raises(RuntimeError, match="durable enqueue"):
            await delete_workspace(db, owner, workspace_id)
        await db.rollback()
        assert await db.get(Item, item_id) is not None
        assert await search_index(db).search(db, "Teardown") == [item_id]
        assert (
            await db.scalar(select(AuditEvent.id).where(AuditEvent.action == "workspace.delete"))
            is None
        )
        monkeypatch.setattr(fake_durable_operations, "enqueue_in_transaction", original_enqueue)
        owner = await db.get(User, owner_id)
        await delete_workspace(db, owner, workspace_id)
    async with persistence_sessions() as fresh:
        assert await fresh.get(Workspace, workspace_id) is None
        assert await search_index(fresh).search(fresh, "Teardown") == []
        for table in ("item_search", "revision_search"):
            assert (await fresh.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0
        assert await fresh.get(PdfAnnotation, identities[0]) is None
        assert await fresh.get(PdfAnnotationReply, identities[1]) is None
    assert await get_object_store().exists(stored.key)  # I/O is deferred until after commit.
    assert fake_durable_operations.enqueues[-1]["attributes"]["object_intent"] == "cleanup"


@pytest.mark.anyio
@pytest.mark.parametrize("bulk", [False, True])
async def test_item_deletion_retires_document_identities_and_cleanup_is_atomic(
    persistence_sessions, fake_durable_operations, monkeypatch, bulk
):
    from quirebase.library import BulkItemAction, apply_bulk_item_action, delete_item

    store = get_object_store()
    stored = [
        await store.put_object(uuid4(), ObjectSuffix.BINARY, content, max_bytes=100)
        for content in (b"pdf", b"thumbnail", b"supplement", b"retained-export")
    ]
    async with persistence_sessions() as db:
        owner_id, workspace_id = await _workspace(db)
        item = Item(
            workspace_id=workspace_id,
            created_by=owner_id,
            work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Retired documents"},
        )
        retained = Item(
            workspace_id=workspace_id,
            created_by=owner_id,
            work={"id": f"urn:uuid:{uuid4()}", "type": "Document", "title": "Retained item"},
        )
        artifact = _artifact(stored[3], workspace_id)
        db.add_all([item, retained, artifact])
        await db.flush()
        revision = FileRevision(
            workspace_id=workspace_id,
            item_id=item.id,
            created_by=owner_id,
            file=_file(stored[0]),
            thumbnail=_file(stored[1]),
            full_text="Retired text",
        )
        attachment = Attachment(
            workspace_id=workspace_id,
            item_id=item.id,
            created_by=owner_id,
            file=_file(stored[2]),
        )
        retained_revision = FileRevision(
            workspace_id=workspace_id,
            item_id=retained.id,
            created_by=owner_id,
            file=_file(stored[0]),
        )
        db.add_all([revision, attachment, retained_revision])
        await db.flush()
        annotation = PdfAnnotation(
            workspace_id=workspace_id,
            file_revision_id=revision.id,
            item_id=item.id,
            page_index=0,
            author_id=owner_id,
            kind="note",
            scope="private",
            payload={},
        )
        db.add(annotation)
        await db.flush()
        reply = PdfAnnotationReply(
            workspace_id=workspace_id,
            annotation_id=annotation.id,
            author_id=owner_id,
            body="Reply",
        )
        db.add(reply)
        await search_index(db).index_item(db, item.id)
        await search_index(db).index_revision(db, revision.id)
        await db.commit()
        item_id, retained_id = item.id, retained.id
        revision_id, attachment_id = revision.id, attachment.id
        annotation_id, reply_id = annotation.id, reply.id
        artifact_id, retained_revision_id = artifact.workflow_id, retained_revision.id

        async def delete():
            owner = await db.get(User, owner_id)
            if bulk:
                await apply_bulk_item_action(
                    db, owner, workspace_id, [item_id], BulkItemAction.delete_items
                )
            else:
                await delete_item(db, owner, workspace_id, item_id)

        enqueue = fake_durable_operations.enqueue_in_transaction

        async def fail_enqueue(*args, **kwargs):
            await asyncio.sleep(0)
            raise RuntimeError("cleanup enqueue unavailable")

        monkeypatch.setattr(fake_durable_operations, "enqueue_in_transaction", fail_enqueue)
        with pytest.raises(RuntimeError, match="cleanup enqueue"):
            await delete()
        await db.rollback()
        for model, identity in (
            (Item, item_id),
            (FileRevision, revision_id),
            (Attachment, attachment_id),
            (PdfAnnotation, annotation_id),
            (PdfAnnotationReply, reply_id),
        ):
            assert await db.get(model, identity) is not None
        assert await search_index(db).search(db, "Retired") == [item_id]
        audit_action = "library.bulk.delete_items" if bulk else "item.delete"
        assert (
            await db.scalar(select(AuditEvent.id).where(AuditEvent.action == audit_action)) is None
        )
        monkeypatch.setattr(fake_durable_operations, "enqueue_in_transaction", enqueue)
        await delete()

    async with persistence_sessions() as fresh:
        for model, identity in (
            (Item, item_id),
            (FileRevision, revision_id),
            (Attachment, attachment_id),
            (PdfAnnotation, annotation_id),
            (PdfAnnotationReply, reply_id),
        ):
            assert await fresh.get(model, identity) is None
        assert await fresh.get(Item, retained_id) is not None
        assert await fresh.get(FileRevision, retained_revision_id) is not None
        assert await fresh.get(ExportArtifact, artifact_id) is not None
        assert await search_index(fresh).search(fresh, "Retired") == []
        assert await fresh.scalar(select(AuditEvent.id).where(AuditEvent.action == audit_action))
    cleanup = fake_durable_operations.enqueues[-1]
    assert set(cleanup["args"][2]) == {receipt.key for receipt in stored[:3]}
    assert cleanup["attributes"]["object_intent"] == "cleanup"
    assert all([await store.exists(receipt.key) for receipt in stored])
