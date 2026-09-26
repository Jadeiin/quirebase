from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.access import Capability, require_workspace_capability
from quirebase.accounts import update_user_status
from quirebase.core.database import Base, make_async_engine
from quirebase.core.errors import (
    PermissionDenied,
    ResourceUnavailable,
    ValidationFailure,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
)
from quirebase.documents import AnnotationReplyCreate, create_annotation_reply
from quirebase.documents.workflows import _lock_upload_authority
from quirebase.library import (
    add_discussion_message,
    add_existing_tag_to_item,
    add_project_discussion_message,
    apply_bulk_item_action,
    commit_import_batch,
)
from quirebase.models import (
    AnnotationKind,
    AnnotationScope,
    FileRevision,
    ImportBatch,
    Item,
    ItemTag,
    PdfAnnotation,
    Project,
    ProjectItem,
    ProjectMember,
    ProjectState,
    ProjectVisibility,
    Tag,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.projects import (
    ProjectMemberConflict,
    add_item_to_project,
    add_project_member,
    create_project,
    join_project,
    rename_project,
    set_project_visibility,
)
from quirebase.workspaces import (
    archive_workspace,
    suspend_workspace_member,
    transfer_workspace_ownership,
)

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.shared_postgres,
    pytest.mark.skipif(
        not os.getenv("QUIREBASE_TEST_POSTGRES_URL"), reason="PostgreSQL is not configured"
    ),
]


@pytest.fixture
async def postgres_sessions():
    engine = make_async_engine(os.environ["QUIREBASE_TEST_POSTGRES_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def _user(db: AsyncSession, prefix: str) -> User:
    user = User(username=f"{prefix}-{uuid4()}", password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    return user


async def _project_annotation_context(
    db: AsyncSession, prefix: str
) -> tuple[str, str, str, str, str]:
    owner = await _user(db, f"{prefix}-owner")
    workspace_id, owner_id = fixture_workspace_id(owner), owner.id
    item = Item(workspace_id=workspace_id, title=prefix, created_by=owner_id)
    project = Project(workspace_id=workspace_id, name=prefix, created_by=owner_id)
    db.add_all([item, project])
    await db.flush()
    assignment = ProjectItem(
        workspace_id=workspace_id,
        project_id=project.id,
        item_id=item.id,
        added_by=owner_id,
    )
    revision = FileRevision(
        workspace_id=workspace_id,
        item_id=item.id,
        object_key=f"objects/{prefix}.pdf",
        size=1,
        original_name=f"{prefix}.pdf",
        created_by=owner_id,
    )
    db.add_all([assignment, revision])
    await db.flush()
    annotation = PdfAnnotation(
        workspace_id=workspace_id,
        file_revision_id=revision.id,
        item_id=item.id,
        page_index=0,
        author_id=owner_id,
        kind=AnnotationKind.note,
        scope=AnnotationScope.project,
        project_item_id=assignment.id,
        body="Reply target",
        payload={"type": "note", "rect": {"x": 1, "y": 1, "width": 1, "height": 1}},
    )
    db.add(annotation)
    await db.commit()
    return workspace_id, owner_id, item.id, assignment.id, annotation.id


async def test_write_authorization_serializes_with_workspace_archive(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "write-race-owner")
        writer = await _user(db, "write-race-writer")
        workspace_id, owner_id, writer_id = fixture_workspace_id(owner), owner.id, writer.id
        item = Item(workspace_id=workspace_id, title="Write race", created_by=owner_id)
        db.add_all([
            item,
            WorkspaceMember(
                workspace_id=workspace_id,
                user_id=writer_id,
                role=WorkspaceRole.reviewer,
                invited_by=owner_id,
            ),
        ])
        await db.commit()
        item_id = item.id

    authorized = asyncio.Event()
    release_write = asyncio.Event()
    archive_started = asyncio.Event()

    async def write_message():
        async with postgres_sessions() as db:
            actor = await db.get(User, writer_id)
            assert actor is not None
            await require_workspace_capability(db, actor, workspace_id, Capability.discussion_write)
            authorized.set()
            await release_write.wait()
            return await add_discussion_message(db, actor, workspace_id, item_id, "Before archive")

    async def archive():
        async with postgres_sessions() as db:
            actor = await db.get(User, owner_id)
            assert actor is not None
            archive_started.set()
            await archive_workspace(db, actor, workspace_id)

    writer_task = asyncio.create_task(write_message())
    await authorized.wait()
    archive_task = asyncio.create_task(archive())
    try:
        await archive_started.wait()
        await asyncio.sleep(0.05)
        assert not archive_task.done()
    finally:
        release_write.set()
        await asyncio.gather(writer_task, archive_task)

    async with postgres_sessions() as db:
        actor = await db.get(User, writer_id)
        assert actor is not None
        with pytest.raises(WorkspaceLifecycleError):
            await add_discussion_message(db, actor, workspace_id, item_id, "After archive")


async def test_project_discussion_waits_for_archive_and_rechecks_state(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "project-archive-race")
        workspace_id, owner_id = fixture_workspace_id(owner), owner.id
        project = Project(
            workspace_id=workspace_id,
            name="Archiving",
            created_by=owner_id,
        )
        db.add(project)
        await db.commit()
        project_id = project.id

    async with postgres_sessions() as archive_db:
        project = await archive_db.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        assert project is not None
        project.state = ProjectState.archived

        started = asyncio.Event()

        async def write_message():
            async with postgres_sessions() as db:
                actor = await db.get(User, owner_id)
                assert actor is not None
                started.set()
                with pytest.raises(WorkspaceLifecycleError):
                    await add_project_discussion_message(
                        db, actor, workspace_id, project_id, "After archive"
                    )

        writer_task = asyncio.create_task(write_message())
        try:
            await started.wait()
            await asyncio.sleep(0.05)
            assert not writer_task.done()
        finally:
            await archive_db.commit()
            await writer_task


async def test_waiting_writer_reloads_workspace_after_archive_commits(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "waiting-write-owner")
        workspace_id, owner_id = fixture_workspace_id(owner), owner.id

    async with postgres_sessions() as governance_db:
        workspace = await governance_db.scalar(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        assert workspace is not None
        workspace.state = WorkspaceState.archived

        started = asyncio.Event()

        async def authorize_write():
            async with postgres_sessions() as db:
                actor = await db.get(User, owner_id)
                assert actor is not None
                started.set()
                with pytest.raises(WorkspaceLifecycleError):
                    await require_workspace_capability(
                        db, actor, workspace_id, Capability.discussion_write
                    )

        writer_task = asyncio.create_task(authorize_write())
        try:
            await started.wait()
            await asyncio.sleep(0.05)
            assert not writer_task.done()
        finally:
            await governance_db.commit()
            await writer_task


async def test_current_membership_partial_unique_serializes_rejoin(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "membership-owner")
        target = await _user(db, "membership-target")
        workspace_id = fixture_workspace_id(owner)
        owner_id = owner.id
        target_id = target.id

    async def add_current_member():
        async with postgres_sessions() as db:
            db.add(
                WorkspaceMember(
                    workspace_id=workspace_id,
                    user_id=target_id,
                    role=WorkspaceRole.viewer,
                    invited_by=owner_id,
                )
            )
            try:
                await db.commit()
                return "committed"
            except IntegrityError:
                await db.rollback()
                return "conflict"

    outcomes = await asyncio.gather(add_current_member(), add_current_member())
    assert sorted(outcomes) == ["committed", "conflict"]


async def test_concurrent_ownership_transfer_reauthorizes_after_root_lock(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "transfer-owner")
        first = await _user(db, "transfer-first")
        second = await _user(db, "transfer-second")
        workspace_id = fixture_workspace_id(owner)
        owner_id = owner.id
        first_member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=first.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        )
        second_member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=second.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        )
        db.add_all([first_member, second_member])
        await db.commit()
        target_ids = (first_member.id, second_member.id)

    gate = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def transfer(target_id: str):
        nonlocal ready
        async with postgres_sessions() as db:
            actor = await db.get(User, owner_id)
            assert actor is not None
            async with ready_lock:
                ready += 1
                if ready == 2:
                    gate.set()
            await gate.wait()
            try:
                await transfer_workspace_ownership(db, actor, workspace_id, target_id)
                return "committed"
            except PermissionDenied:
                await db.rollback()
                return "denied"

    outcomes = await asyncio.gather(*(transfer(target_id) for target_id in target_ids))
    assert sorted(outcomes) == ["committed", "denied"]

    async with postgres_sessions() as db:
        workspace = await db.get(Workspace, workspace_id)
        assert workspace is not None
        owner_count = await db.scalar(
            select(func.count(WorkspaceMember.id)).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == WorkspaceRole.owner,
                WorkspaceMember.terminated_at.is_(None),
            )
        )
        assert owner_count == 1
        assert workspace.owner_id in {first.id, second.id}


async def test_ownership_transfer_serializes_with_target_deactivation(
    postgres_sessions,
):
    async with postgres_sessions() as db:
        owner = await _user(db, "transfer-deactivate-owner")
        admin = await _user(db, "transfer-deactivate-admin")
        target = await _user(db, "transfer-deactivate-target")
        admin.role = "administrator"

        target_workspace_id = fixture_workspace_id(target)
        admin_membership = WorkspaceMember(
            workspace_id=target_workspace_id,
            user_id=admin.id,
            role=WorkspaceRole.admin,
            invited_by=target.id,
        )
        db.add(admin_membership)
        await db.flush()
        await transfer_workspace_ownership(db, target, target_workspace_id, admin_membership.id)

        workspace_id = fixture_workspace_id(owner)
        target_membership = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=target.id,
            role=WorkspaceRole.editor,
            invited_by=owner.id,
        )
        db.add(target_membership)
        await db.commit()
        owner_id = owner.id
        admin_id = admin.id
        target_id = target.id
        target_membership_id = target_membership.id

    transfer_started = asyncio.Event()
    deactivation_started = asyncio.Event()

    async def transfer():
        async with postgres_sessions() as db:
            actor = await db.get(User, owner_id)
            assert actor is not None
            transfer_started.set()
            await transfer_workspace_ownership(db, actor, workspace_id, target_membership_id)
            return "transferred"

    async def deactivate():
        async with postgres_sessions() as db:
            actor = await db.get(User, admin_id)
            assert actor is not None
            deactivation_started.set()
            try:
                await update_user_status(db, actor, target_id, active=False)
            except PermissionDenied:
                await db.rollback()
                return "denied"
            return "deactivated"

    async with postgres_sessions() as blocker_db:
        workspace = await blocker_db.scalar(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        assert workspace is not None

        transfer_task = asyncio.create_task(transfer())
        await transfer_started.wait()
        await asyncio.sleep(0.05)
        assert not transfer_task.done()

        deactivation_task = asyncio.create_task(deactivate())
        await deactivation_started.wait()
        await asyncio.sleep(0.05)
        assert not deactivation_task.done()

        await blocker_db.commit()
        outcomes = await asyncio.wait_for(
            asyncio.gather(transfer_task, deactivation_task, return_exceptions=True),
            timeout=5,
        )

    assert outcomes == ["transferred", "denied"]

    async with postgres_sessions() as db:
        workspace = await db.get(Workspace, workspace_id)
        target = await db.get(User, target_id)
        assert workspace is not None
        assert target is not None
        assert workspace.owner_id == target.id
        assert target.active is True


async def test_upload_finalizer_and_deactivation_follow_user_workspace_lock_order(
    postgres_sessions,
):
    async with postgres_sessions() as db:
        administrator = await _user(db, "upload-deactivate-admin")
        administrator.role = "administrator"
        actor = User(username=f"upload-deactivate-actor-{uuid4()}", password_hash="unused")
        db.add(actor)
        await db.flush()
        workspace_id = fixture_workspace_id(administrator)
        db.add(
            WorkspaceMember(
                workspace_id=workspace_id,
                user_id=actor.id,
                role=WorkspaceRole.editor,
                invited_by=administrator.id,
            )
        )
        item = Item(
            workspace_id=workspace_id,
            title="Upload finalizer lock order",
            created_by=administrator.id,
        )
        db.add(item)
        await db.commit()
        administrator_id, actor_id, item_id = administrator.id, actor.id, item.id

    finalizer_started = asyncio.Event()
    deactivation_started = asyncio.Event()

    async def finalize_upload() -> str:
        async with postgres_sessions() as db:
            finalizer_started.set()
            await _lock_upload_authority(db, actor_id, workspace_id, item_id)
            await db.commit()
            return "finalized"

    async def deactivate_actor() -> str:
        async with postgres_sessions() as db:
            administrator = await db.get(User, administrator_id)
            assert administrator is not None
            deactivation_started.set()
            await update_user_status(db, administrator, actor_id, active=False)
            return "deactivated"

    async with postgres_sessions() as blocker_db:
        workspace = await blocker_db.scalar(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        assert workspace is not None

        finalizer_task = asyncio.create_task(finalize_upload())
        await finalizer_started.wait()
        await asyncio.sleep(0.05)
        assert not finalizer_task.done()

        deactivation_task = asyncio.create_task(deactivate_actor())
        await deactivation_started.wait()
        await asyncio.sleep(0.05)
        assert not deactivation_task.done()

        await blocker_db.commit()
        outcomes = await asyncio.wait_for(
            asyncio.gather(finalizer_task, deactivation_task, return_exceptions=True),
            timeout=5,
        )

    assert outcomes == ["finalized", "deactivated"]


async def test_import_confirmation_and_deactivation_follow_user_workspace_lock_order(
    postgres_sessions,
    monkeypatch,
):
    index = AsyncMock()
    monkeypatch.setattr("quirebase.library.imports.search_index", lambda _db: index)

    async with postgres_sessions() as db:
        administrator = await _user(db, "import-deactivate-admin")
        administrator.role = "administrator"
        actor = User(username=f"import-deactivate-actor-{uuid4()}", password_hash="unused")
        db.add(actor)
        await db.flush()
        workspace_id = fixture_workspace_id(administrator)
        db.add(
            WorkspaceMember(
                workspace_id=workspace_id,
                user_id=actor.id,
                role=WorkspaceRole.editor,
                invited_by=administrator.id,
            )
        )
        batch = ImportBatch(
            workspace_id=workspace_id,
            actor_id=administrator.id,
            file_format="bibtex",
            records='[{"title": "Confirmed without a deadlock"}]',
            errors="[]",
            status="ready",
        )
        db.add(batch)
        await db.commit()
        administrator_id, actor_id, batch_id = administrator.id, actor.id, batch.id

    confirmation_started = asyncio.Event()
    deactivation_started = asyncio.Event()

    async def confirm_import() -> str:
        async with postgres_sessions() as db:
            actor = await db.get(User, actor_id)
            assert actor is not None
            confirmation_started.set()
            await commit_import_batch(db, actor, workspace_id, batch_id)
            return "confirmed"

    async def deactivate_actor() -> str:
        async with postgres_sessions() as db:
            administrator = await db.get(User, administrator_id)
            assert administrator is not None
            deactivation_started.set()
            await update_user_status(db, administrator, actor_id, active=False)
            return "deactivated"

    async with postgres_sessions() as blocker_db:
        workspace = await blocker_db.scalar(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        assert workspace is not None

        confirmation_task = asyncio.create_task(confirm_import())
        await confirmation_started.wait()
        await asyncio.sleep(0.05)
        assert not confirmation_task.done()

        deactivation_task = asyncio.create_task(deactivate_actor())
        await deactivation_started.wait()
        await asyncio.sleep(0.05)
        assert not deactivation_task.done()

        await blocker_db.commit()
        outcomes = await asyncio.wait_for(
            asyncio.gather(confirmation_task, deactivation_task, return_exceptions=True),
            timeout=5,
        )

    assert outcomes == ["confirmed", "deactivated"]
    index.index_item.assert_awaited_once()


async def test_concurrent_project_renames_do_not_upgrade_shared_workspace_locks(
    postgres_sessions,
):
    async with postgres_sessions() as db:
        owner = await _user(db, "rename-lock-owner")
        workspace_id = fixture_workspace_id(owner)
        project = await create_project(db, owner, workspace_id, "Initial name")
        project_id = project.id
        owner_id = owner.id

    gate = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def rename(name: str):
        nonlocal ready
        async with postgres_sessions() as db:
            actor = await db.get(User, owner_id)
            assert actor is not None
            async with ready_lock:
                ready += 1
                if ready == 2:
                    gate.set()
            await gate.wait()
            await rename_project(db, actor, workspace_id, project_id, name)

    await asyncio.wait_for(asyncio.gather(rename("First name"), rename("Second name")), timeout=5)

    async with postgres_sessions() as db:
        project = await db.get(Project, project_id)
        assert project is not None
        assert project.name in {"First name", "Second name"}


async def test_project_participation_add_races_switch_to_workspace_mode(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "participation-owner")
        target = await _user(db, "participation-target")
        workspace_id = fixture_workspace_id(owner)
        owner_id = owner.id
        target_id = target.id
        target_username = target.username
        membership = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=target_id,
            role=WorkspaceRole.editor,
            invited_by=owner_id,
        )
        db.add(membership)
        await db.commit()
        project = await create_project(
            db, owner, workspace_id, "Concurrent participation", ProjectVisibility.managed
        )
        project_id = project.id

    gate = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def change_participation(switch_to_workspace: bool):
        nonlocal ready
        async with postgres_sessions() as db:
            actor = await db.get(User, owner_id)
            assert actor is not None
            async with ready_lock:
                ready += 1
                if ready == 2:
                    gate.set()
            await gate.wait()
            try:
                if switch_to_workspace:
                    await set_project_visibility(
                        db, actor, workspace_id, project_id, ProjectVisibility.workspace
                    )
                else:
                    await add_project_member(db, actor, workspace_id, project_id, target_username)
                return "committed"
            except ProjectMemberConflict:
                await db.rollback()
                return "rejected"

    outcomes = await asyncio.gather(change_participation(True), change_participation(False))
    assert sorted(outcomes) in (["committed", "committed"], ["committed", "rejected"])

    async with postgres_sessions() as db:
        project = await db.get(Project, project_id)
        assert project is not None
        assert project.visibility is ProjectVisibility.workspace
        participants = await db.scalar(
            select(func.count(ProjectMember.id)).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == project_id,
            )
        )
        assert participants == 0


async def test_reply_create_waits_for_annotation_moderation_and_rechecks(postgres_sessions):
    async with postgres_sessions() as db:
        (
            workspace_id,
            owner_id,
            item_id,
            _assignment_id,
            annotation_id,
        ) = await _project_annotation_context(db, "reply-moderation")

    async with postgres_sessions() as moderator_db:
        annotation = await moderator_db.scalar(
            select(PdfAnnotation).where(PdfAnnotation.id == annotation_id).with_for_update()
        )
        assert annotation is not None
        annotation.locked_at = datetime.now(UTC)
        await moderator_db.flush()

        started = asyncio.Event()

        async def reply() -> str:
            async with postgres_sessions() as db:
                actor = await db.get(User, owner_id)
                assert actor is not None
                started.set()
                try:
                    await create_annotation_reply(
                        db,
                        actor,
                        workspace_id,
                        item_id,
                        annotation_id,
                        AnnotationReplyCreate(id=uuid4(), body="Concurrent reply"),
                    )
                except PermissionDenied:
                    await db.rollback()
                    return "rejected"
                return "committed"

        reply_task = asyncio.create_task(reply())
        try:
            await started.wait()
            await asyncio.sleep(0.05)
            assert not reply_task.done()
        finally:
            await moderator_db.commit()
        assert await asyncio.wait_for(reply_task, timeout=5) == "rejected"


async def test_reply_create_waits_for_project_item_detachment_and_rechecks(postgres_sessions):
    async with postgres_sessions() as db:
        (
            workspace_id,
            owner_id,
            item_id,
            assignment_id,
            annotation_id,
        ) = await _project_annotation_context(db, "reply-detachment")

    async with postgres_sessions() as detach_db:
        assignment = await detach_db.scalar(
            select(ProjectItem).where(ProjectItem.id == assignment_id).with_for_update()
        )
        assert assignment is not None
        await detach_db.delete(assignment)
        await detach_db.flush()

        started = asyncio.Event()

        async def reply() -> str:
            async with postgres_sessions() as db:
                actor = await db.get(User, owner_id)
                assert actor is not None
                started.set()
                try:
                    await create_annotation_reply(
                        db,
                        actor,
                        workspace_id,
                        item_id,
                        annotation_id,
                        AnnotationReplyCreate(id=uuid4(), body="Concurrent reply"),
                    )
                except ResourceUnavailable:
                    await db.rollback()
                    return "rejected"
                return "committed"

        reply_task = asyncio.create_task(reply())
        try:
            await started.wait()
            await asyncio.sleep(0.05)
            assert not reply_task.done()
        finally:
            await detach_db.commit()
        assert await asyncio.wait_for(reply_task, timeout=5) == "rejected"


async def test_bulk_project_assignment_translates_item_delete_race(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "bulk-delete-race-owner")
        workspace_id, owner_id = fixture_workspace_id(owner), owner.id
        item = Item(workspace_id=workspace_id, title="Delete race", created_by=owner_id)
        project = Project(workspace_id=workspace_id, name="Delete race", created_by=owner_id)
        db.add_all([item, project])
        await db.commit()
        item_id, project_id = item.id, project.id

    async with postgres_sessions() as delete_db:
        item = await delete_db.scalar(select(Item).where(Item.id == item_id).with_for_update())
        assert item is not None
        await delete_db.delete(item)
        await delete_db.flush()

        started = asyncio.Event()

        async def assign() -> str:
            async with postgres_sessions() as db:
                actor = await db.get(User, owner_id)
                assert actor is not None
                started.set()
                try:
                    await apply_bulk_item_action(
                        db,
                        actor,
                        workspace_id,
                        item_ids=[item_id],
                        action="add_project",
                        project_id=project_id,
                    )
                except ValidationFailure:
                    assert await db.scalar(select(func.count()).select_from(Project)) == 1
                    return "rejected"
                return "committed"

        assignment_task = asyncio.create_task(assign())
        try:
            await started.wait()
            await asyncio.sleep(0.05)
            assert not assignment_task.done()
        finally:
            await delete_db.commit()
        assert await asyncio.wait_for(assignment_task, timeout=5) == "rejected"


async def test_open_project_join_races_workspace_member_suspension(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "join-race-owner")
        target = await _user(db, "join-race-target")
        workspace_id = fixture_workspace_id(owner)
        owner_id, target_id = owner.id, target.id
        membership = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=target_id,
            role=WorkspaceRole.editor,
            invited_by=owner_id,
        )
        db.add(membership)
        await db.commit()
        membership_id = membership.id
        project = await create_project(
            db, owner, workspace_id, "Open join race", ProjectVisibility.open
        )
        project_id = project.id

    gate = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def change_membership(suspend: bool):
        nonlocal ready
        async with postgres_sessions() as db:
            actor_id = target_id if not suspend else owner_id
            actor = await db.get(User, actor_id)
            assert actor is not None
            async with ready_lock:
                ready += 1
                if ready == 2:
                    gate.set()
            await gate.wait()
            try:
                if suspend:
                    await suspend_workspace_member(db, actor, workspace_id, membership_id)
                else:
                    await join_project(db, actor, workspace_id, project_id)
                return "committed"
            except WorkspaceMembershipRequired:
                await db.rollback()
                return "rejected"

    outcomes = await asyncio.gather(change_membership(False), change_membership(True))
    assert sorted(outcomes) in (["committed", "committed"], ["committed", "rejected"])

    async with postgres_sessions() as db:
        membership = await db.get(WorkspaceMember, membership_id)
        assert membership is not None
        assert membership.state.value == "suspended"
        participant = await db.scalar(
            select(ProjectMember).where(
                ProjectMember.workspace_id == workspace_id,
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == target_id,
            )
        )
        if "rejected" in outcomes:
            assert participant is None
        else:
            assert participant is not None


async def test_concurrent_project_item_add_is_idempotent(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "assignment-owner")
        workspace_id = fixture_workspace_id(owner)
        owner_id = owner.id
        project = await create_project(db, owner, workspace_id, "Working set")
        item = Item(workspace_id=workspace_id, title="Shared assignment", created_by=owner_id)
        db.add(item)
        await db.commit()
        project_id, item_id = project.id, item.id

    gate = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def add():
        nonlocal ready
        async with postgres_sessions() as db:
            actor = await db.get(User, owner_id)
            assert actor is not None
            async with ready_lock:
                ready += 1
                if ready == 2:
                    gate.set()
            await gate.wait()
            await add_item_to_project(db, actor, workspace_id, project_id, item_id)

    await asyncio.gather(add(), add())
    async with postgres_sessions() as db:
        count = await db.scalar(
            select(func.count(ProjectItem.id)).where(
                ProjectItem.workspace_id == workspace_id,
                ProjectItem.project_id == project_id,
                ProjectItem.item_id == item_id,
            )
        )
        assert count == 1


async def test_concurrent_item_tag_add_is_idempotent(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "tag-owner")
        workspace_id = fixture_workspace_id(owner)
        owner_id = owner.id
        item = Item(workspace_id=workspace_id, title="Tagged once", created_by=owner_id)
        tag = Tag(
            workspace_id=workspace_id,
            name="Evidence",
            normalized_name="evidence",
            created_by=owner_id,
        )
        db.add_all([item, tag])
        await db.commit()
        item_id, tag_id = item.id, tag.id

    gate = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def add():
        nonlocal ready
        async with postgres_sessions() as db:
            actor = await db.get(User, owner_id)
            assert actor is not None
            async with ready_lock:
                ready += 1
                if ready == 2:
                    gate.set()
            await gate.wait()
            await add_existing_tag_to_item(db, actor, workspace_id, item_id, tag_id)

    await asyncio.gather(add(), add())
    async with postgres_sessions() as db:
        count = await db.scalar(
            select(func.count(ItemTag.item_id)).where(
                ItemTag.workspace_id == workspace_id,
                ItemTag.item_id == item_id,
                ItemTag.tag_id == tag_id,
            )
        )
        assert count == 1
