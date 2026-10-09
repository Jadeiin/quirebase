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
from quirebase.core.errors import PermissionDenied
from quirebase.core.storage import ObjectSuffix, get_object_store
from quirebase.core.workflows import object_reservation_attributes
from quirebase.documents import (
    delete_unreferenced_objects,
    list_expired_export_artifacts,
    retire_expired_export_artifacts,
)
from quirebase.library import ItemSection, open_item_section
from quirebase.models import (
    Attachment,
    AuditEvent,
    ExportArtifact,
    FileRevision,
    ImportBatch,
    Item,
    LoginSession,
    PdfAnnotation,
    PdfAnnotationObject,
    PdfAnnotationReply,
    Project,
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
    list_item_organize_projects,
    list_workspace_projects,
    open_project_workspace,
)
from quirebase.search import search_index
from quirebase.workspaces import permanently_delete_workspace

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
        item = Item(workspace_id=workspace_id, title="Late reference", created_by=owner_id)
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
            item = Item(workspace_id=workspace_id, title="Confirmed", created_by=owner_id)
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
async def test_owner_deactivation_guard_preserves_status_session_and_audit(
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
        with pytest.raises(PermissionDenied, match="transfer Workspace ownership"):
            await update_user_status(db, admin, owner_id, False)
        assert owner.active
        assert await db.get(LoginSession, session_id) is not None
        assert (
            await db.scalar(
                select(AuditEvent.id).where(AuditEvent.action == "admin.user.status_update")
            )
            is None
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
        item = Item(workspace_id=workspace_id, title="Options", created_by=owner_id)
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
            state=ProjectState.deleted,
        )
        db.add_all([*implicit, open_project, managed, archived, deleted])
        await db.commit()
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
        item = Item(workspace_id=workspace_id, title="Teardown searchable", created_by=owner_id)
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
            await permanently_delete_workspace(db, owner, workspace_id)
        await db.rollback()
        assert await db.get(Item, item_id) is not None
        assert await search_index(db).search(db, "Teardown") == [item_id]
        assert (
            await db.scalar(select(AuditEvent.id).where(AuditEvent.action == "workspace.delete"))
            is None
        )
        monkeypatch.setattr(fake_durable_operations, "enqueue_in_transaction", original_enqueue)
        owner = await db.get(User, owner_id)
        await permanently_delete_workspace(db, owner, workspace_id)
    async with persistence_sessions() as fresh:
        assert await fresh.get(Workspace, workspace_id) is None
        assert await search_index(fresh).search(fresh, "Teardown") == []
        for table in ("item_search", "revision_search"):
            assert (await fresh.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0
        assert not list(
            await fresh.scalars(
                select(PdfAnnotationObject.id).where(PdfAnnotationObject.id.in_(identities))
            )
        )
    assert await get_object_store().exists(stored.key)  # I/O is deferred until after commit.
    assert fake_durable_operations.enqueues[-1]["attributes"]["object_intent"] == "cleanup"


@pytest.mark.anyio
@pytest.mark.concurrency_case("upload-finalization")
async def test_workspace_teardown_fences_waiting_finalizer_and_releases_its_orphan(
    postgres_sessions, postgres_search_tables, postgres_race, fake_durable_operations, monkeypatch
):
    from quirebase.documents.workflows import _lock_upload_authority

    store = get_object_store()
    pending = await store.put_object(uuid4(), ObjectSuffix.PDF, b"pending", max_bytes=100)
    async with postgres_sessions() as db:
        owner_id, workspace_id = await _workspace(db)
        item = Item(workspace_id=workspace_id, title="Deleted during upload", created_by=owner_id)
        db.add(item)
        workspace = await db.get(Workspace, workspace_id)
        workspace.state = WorkspaceState.archived
        workspace.archived_at = datetime.now(UTC) - timedelta(days=3650)
        await db.commit()
        item_id = item.id
    await fake_durable_operations.enqueue(
        "documents.upload_revision",
        queue_name="documents.upload",
        workflow_id="late-upload",
        attributes=object_reservation_attributes([pending.key]),
    )
    ready, release = asyncio.Event(), asyncio.Event()

    async def teardown():
        async with postgres_race.session("teardown") as db:
            owner = await db.get(User, owner_id)
            original_commit = db.commit

            async def pause_commit():
                ready.set()
                await release.wait()
                await original_commit()

            monkeypatch.setattr(db, "commit", pause_commit)
            await permanently_delete_workspace(db, owner, workspace_id)

    async def finalize():
        async with postgres_race.session("finalizer") as db:
            with pytest.raises(ValueError, match="Workspace is no longer writable"):
                await _lock_upload_authority(db, owner_id, workspace_id, item_id)
            return await delete_unreferenced_objects(
                db, [pending.key], ignore_workflow_id="late-upload"
            )

    postgres_race.start("teardown", teardown())
    await asyncio.wait_for(ready.wait(), timeout=5)
    postgres_race.start("finalizer", finalize())
    await postgres_race.wait_blocked("finalizer", "teardown")
    release.set()
    await postgres_race.join("teardown")
    assert await postgres_race.join("finalizer") == (pending.key,)
    assert not await store.exists(pending.key)
    async with postgres_race.session("verify") as db:
        assert await db.get(Workspace, workspace_id) is None
        assert await db.scalar(select(FileRevision.id)) is None
