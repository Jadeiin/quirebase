from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from advanced_alchemy.types import FileObject
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.access import ResourceAction, require_workspace_action, resolve_workspace_context
from quirebase.accounts import (
    change_own_password,
    change_user_role,
    reset_user_password,
    throttling,
    update_user_status,
)
from quirebase.accounts._persistence import LoginThrottleRepository
from quirebase.accounts.throttling import (
    THROTTLE_WINDOW,
    check_login_throttle,
    clear_login_failures,
    record_login_failure,
)
from quirebase.audit import query_events
from quirebase.core.errors import (
    PermissionDenied,
    ProjectLifecycleError,
    ResourceUnavailable,
    ValidationFailure,
    VersionConflict,
    WorkspaceLifecycleError,
    WorkspaceMembershipRequired,
    WorkspaceUnavailable,
)
from quirebase.documents import (
    AnnotationReplyCreate,
    AnnotationReplyUpdate,
    AnnotationUpdate,
    create_annotation_reply,
    update_annotation_reply,
    update_document_annotation,
)
from quirebase.documents.workflows import _lock_upload_authority
from quirebase.library import (
    ItemMetadata,
    ItemMetadataData,
    ItemSection,
    TagConflict,
    add_discussion_message,
    add_existing_tag_to_item,
    add_project_discussion_message,
    apply_bulk_item_action,
    commit_import_batch,
    delete_discussion_message,
    item_sections,
    moderate_project_discussion_message,
    open_item_section,
    remove_tag_from_item,
    revise_item_metadata,
    search_library,
    stage_import_batch,
)
from quirebase.library._persistence import ItemTagRepository
from quirebase.library.authors import AuthorService
from quirebase.library.citations import CitationStyleService, create_custom_citation_style
from quirebase.models import (
    AnnotationKind,
    AnnotationScope,
    AttachmentRole,
    AuditEvent,
    Author,
    CitationStyle,
    DiscussionMessage,
    FileRevision,
    ImportBatch,
    Item,
    ItemRead,
    ItemTag,
    LoginThrottle,
    PdfAnnotation,
    PdfAnnotationReply,
    Project,
    ProjectItem,
    ProjectParticipant,
    ProjectParticipation,
    ProjectState,
    SystemSetting,
    Tag,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceState,
)
from quirebase.operations.settings import RuntimeSettingsService, update_runtime_settings
from quirebase.projects import (
    ProjectParticipationConflict,
    add_item_to_project,
    add_items_to_project,
    add_project_participant,
    create_project,
    join_project,
    leave_project,
    remove_project_participant,
    rename_project,
    set_project_participation,
)
from quirebase.workspaces import (
    archive_workspace,
    freeze_workspace_governance,
    invite_workspace_member,
    list_workspaces,
    list_workspaces_for_governance,
    suspend_workspace_member,
    transfer_workspace_ownership,
    workspace_owner_ids,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.shared_postgres,
    pytest.mark.skipif(
        not os.getenv("QUIREBASE_TEST_POSTGRES_URL"), reason="PostgreSQL is not configured"
    ),
]


async def _user(db: AsyncSession, prefix: str) -> User:
    user = User(username=f"{prefix}-{uuid4()}", password_hash="unused")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    return user


@pytest.mark.concurrency_case("login-throttle")
@pytest.mark.parametrize("clear_before_insert", [False, True])
async def test_login_failure_upsert_increments_or_recreates_a_cleared_counter(
    postgres_sessions, postgres_race, monkeypatch, clear_before_insert
):
    identity = "a" * 64
    read_at = datetime(2026, 10, 8, tzinfo=UTC)
    monkeypatch.setattr(throttling, "datetime", SimpleNamespace(now=lambda _timezone: read_at))
    first_at = read_at
    inserting, resume = asyncio.Event(), asyncio.Event()

    async def first_failure():
        async with postgres_race.session("first") as db:
            scalar = db.scalar

            async def paused_scalar(statement, *args, **kwargs):
                if statement.is_insert and statement.table.name == LoginThrottle.__tablename__:
                    inserting.set()
                    postgres_race.note("counter.before_upsert", actor="first")
                    await asyncio.wait_for(resume.wait(), timeout=5)
                return await scalar(statement, *args, **kwargs)

            monkeypatch.setattr(db, "scalar", paused_scalar)
            await record_login_failure(db, identity)

    postgres_race.start("first", first_failure())
    await asyncio.wait_for(inserting.wait(), timeout=5)
    try:
        read_at += timedelta(seconds=1)
        async with postgres_race.session("second") as db:
            await record_login_failure(db, identity)
        if clear_before_insert:
            async with postgres_race.session("clear") as db:
                await clear_login_failures(db, identity)
    finally:
        resume.set()
    await postgres_race.join("first")
    async with postgres_race.session("verify") as db:
        row = await db.get(LoginThrottle, identity)
        assert row.failures == (1 if clear_before_insert else 2)
        assert row.window_started_at == (first_at if clear_before_insert else read_at)


@pytest.mark.concurrency_case("login-throttle")
async def test_concurrent_first_login_failures_wait_and_preserve_both_counts(
    postgres_sessions, postgres_race
):
    identity = "c" * 64
    now = datetime.now(UTC)

    async def second_failure():
        async with postgres_race.session("second") as db:
            await record_login_failure(db, identity)

    async with postgres_race.session("first") as db:
        await LoginThrottleRepository(session=db).record_failure(
            identity, now, now - THROTTLE_WINDOW
        )
        postgres_race.start("second", second_failure())
        await postgres_race.wait_blocked("second", "first")
        await db.commit()
        await postgres_race.join("second")

    async with postgres_sessions() as db:
        row = await db.get(LoginThrottle, identity)
        assert row.failures == 2
        assert row.window_started_at == now


@pytest.mark.concurrency_case("login-throttle")
async def test_expired_login_check_does_not_delete_a_concurrently_reset_window(
    postgres_sessions, postgres_race, monkeypatch
):
    identity = "b" * 64
    now = datetime(2026, 10, 8, tzinfo=UTC)
    monkeypatch.setattr(throttling, "datetime", SimpleNamespace(now=lambda _timezone: now))
    async with postgres_sessions() as db:
        db.add(
            LoginThrottle(
                identity_hash=identity,
                failures=10,
                window_started_at=now - THROTTLE_WINDOW - timedelta(seconds=1),
            )
        )
        await db.commit()
    expired_read, resume = asyncio.Event(), asyncio.Event()

    async def check():
        async with postgres_race.session("check") as db:
            scalar = db.scalar

            async def paused_scalar(statement, *args, **kwargs):
                result = await scalar(statement, *args, **kwargs)
                if (
                    statement.is_select
                    and statement.column_descriptions[0].get("entity") is LoginThrottle
                ):
                    assert result.window_started_at < now - THROTTLE_WINDOW
                    expired_read.set()
                    await asyncio.wait_for(resume.wait(), timeout=5)
                return result

            monkeypatch.setattr(db, "scalar", paused_scalar)
            await check_login_throttle(db, identity)

    postgres_race.start("check", check())
    await asyncio.wait_for(expired_read.wait(), timeout=5)
    try:
        async with postgres_race.session("failure") as db:
            await record_login_failure(db, identity)
    finally:
        resume.set()
    await postgres_race.join("check")
    async with postgres_race.session("verify") as db:
        row = await db.get(LoginThrottle, identity)
        assert (row.failures, row.window_started_at) == (1, now)


@pytest.mark.concurrency_case("item-reading")
async def test_item_reading_upsert_keeps_a_competing_readers_newer_timestamp(
    postgres_sessions, postgres_race, monkeypatch
):
    async with postgres_sessions() as db:
        owner = await _user(db, "reading-gap")
        workspace_id, owner_id = fixture_workspace_id(owner), owner.id
        item = Item(workspace_id=workspace_id, title="Reading gap", created_by=owner_id)
        db.add(item)
        await db.commit()
        item_id = item.id

    inserting, resume = asyncio.Event(), asyncio.Event()
    read_at = datetime(2026, 10, 8, tzinfo=UTC)
    monkeypatch.setattr(item_sections, "datetime", SimpleNamespace(now=lambda _timezone: read_at))

    async def first_read():
        async with postgres_race.session("first") as db:
            execute = db.execute

            async def paused_execute(statement, *args, **kwargs):
                if (
                    statement.is_insert
                    and statement.table.name == ItemRead.__tablename__
                    and not inserting.is_set()
                ):
                    postgres_race.note("reading.before_upsert", actor="first")
                    inserting.set()
                    await asyncio.wait_for(resume.wait(), timeout=5)
                return await execute(statement, *args, **kwargs)

            monkeypatch.setattr(db, "execute", paused_execute)
            actor = await db.get(User, owner_id)
            context = await resolve_workspace_context(db, actor, workspace_id)
            return await open_item_section(db, context, item_id, ItemSection.overview)

    async def second_read():
        async with postgres_race.session("second") as db:
            actor = await db.get(User, owner_id)
            context = await resolve_workspace_context(db, actor, workspace_id)
            return await open_item_section(db, context, item_id, ItemSection.metadata)

    postgres_race.start("first", first_read())
    await asyncio.wait_for(inserting.wait(), timeout=5)
    try:
        read_at += timedelta(seconds=1)
        postgres_race.start("second", second_read())
        assert (await postgres_race.join("second")).item.id == item_id
    finally:
        resume.set()
    # The older reader takes the native update path without overwriting the
    # newer timestamp committed by the second.
    assert (await postgres_race.join("first")).item.id == item_id
    async with postgres_race.session("verify") as db:
        reads = (await db.scalars(select(ItemRead).where(ItemRead.item_id == item_id))).all()
        assert len(reads) == 1
        assert reads[0].last_read_at == read_at


@pytest.mark.concurrency_case("workspace-read-delete")
@pytest.mark.parametrize("surface", ["list", "detail", "admin"])
async def test_workspace_read_tolerates_committed_root_deletion(postgres_sessions, surface):
    async with postgres_sessions() as setup_db:
        owner = await _user(setup_db, "workspace-read-delete")
        workspace_id, owner_id = fixture_workspace_id(owner), owner.id
        if surface == "admin":
            owner.role = "administrator"
            await setup_db.commit()

    async with postgres_sessions() as read_db:
        owner = await read_db.get(User, owner_id)
        if surface == "detail":
            context = await resolve_workspace_context(read_db, owner, workspace_id)
            workspace_ids = {context.workspace_id}
        elif surface == "list":
            rows = (await list_workspaces(read_db, owner))[0]
            workspace_ids = {workspace.id for workspace, _member in rows}
        else:
            rows = await list_workspaces_for_governance(read_db, owner)
            workspace_ids = {workspace.id for workspace in rows}
        assert workspace_ids == {workspace_id}

        # Commit the root cascade after the initial read. Owner projection must
        # tolerate deletion without requiring the Web application's static build.
        async with postgres_sessions() as delete_db:
            workspace = await delete_db.get(Workspace, workspace_id)
            await delete_db.delete(workspace)
            await delete_db.commit()
        assert await workspace_owner_ids(read_db, workspace_ids) == {}


@pytest.mark.concurrency_case("discussion-root-delete")
@pytest.mark.parametrize("root", ["workspace", "project"])
async def test_project_discussion_moderation_waits_for_root_deletion(
    postgres_sessions, postgres_race, root
):
    async with postgres_sessions() as db:
        owner = await _user(db, "discussion-moderator")
        author = await _user(db, "discussion-author")
        workspace_id, owner_id = fixture_workspace_id(owner), owner.id
        db.add(
            WorkspaceMember(workspace_id=workspace_id, user_id=author.id, role=WorkspaceRole.editor)
        )
        project = Project(workspace_id=workspace_id, name="Discussion", created_by=owner_id)
        db.add(project)
        await db.commit()
        message = await add_project_discussion_message(
            db, author, workspace_id, project.id, "Moderate this message"
        )
        project_id, message_id = project.id, message.id
        if root == "workspace":
            await archive_workspace(db, owner, workspace_id)

    model, root_id = (Workspace, workspace_id) if root == "workspace" else (Project, project_id)
    async with postgres_race.session("delete") as delete_db:
        resource = await delete_db.scalar(
            select(model).where(model.id == root_id).with_for_update()
        )

        async def moderate():
            async with postgres_race.session("moderate") as moderation_db:
                actor = await moderation_db.get(User, owner_id)
                try:
                    await moderate_project_discussion_message(
                        moderation_db, actor, workspace_id, project_id, message_id, "Spam"
                    )
                except (WorkspaceUnavailable, ResourceUnavailable):
                    await moderation_db.rollback()
                    return "rejected"
                return "committed"

        postgres_race.start("moderate", moderate())
        await postgres_race.wait_blocked("moderate", "delete")
        # The parent's cascade must finish while moderation waits at the root.
        await delete_db.delete(resource)
        await delete_db.flush()
        await delete_db.commit()
        assert await postgres_race.join("moderate") == "rejected"


async def _project_annotation_context(
    db: AsyncSession,
    prefix: str,
    *,
    annotation_scope: AnnotationScope = AnnotationScope.project,
) -> tuple[str, str, str, str, str, str]:
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
        created_by=owner_id,
        file=FileObject(
            backend="documents",
            filename=f"objects/{prefix}.pdf",
            size=1,
            content_type="application/pdf",
            metadata={"original_name": f"{prefix}.pdf"},
        ),
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
        scope=annotation_scope,
        project_item_id=(assignment.id if annotation_scope is AnnotationScope.project else None),
        body="Reply target",
        payload={"type": "note", "rect": {"x": 1, "y": 1, "width": 1, "height": 1}},
    )
    db.add(annotation)
    await db.commit()
    return workspace_id, owner_id, item.id, project.id, assignment.id, annotation.id


@pytest.mark.concurrency_case("annotation-version")
@pytest.mark.parametrize("kind", ["annotation", "reply"])
async def test_annotation_edits_with_one_version_have_one_commit_and_audit(
    postgres_sessions, postgres_race, monkeypatch, kind
):
    async with postgres_sessions() as db:
        (
            workspace_id,
            owner_id,
            item_id,
            _project_id,
            _assignment_id,
            annotation_id,
        ) = await _project_annotation_context(
            db, "annotation-version", annotation_scope=AnnotationScope.private
        )
        annotation = await db.get(PdfAnnotation, annotation_id)
        revision = await db.get(FileRevision, annotation.file_revision_id)
        revision.processing_state = "ready"
        revision.page_count = 1
        revision.page_geometry = [[0, 0, 100, 100]]
        target_id = annotation_id
        if kind == "reply":
            reply = PdfAnnotationReply(
                workspace_id=workspace_id,
                annotation_id=annotation_id,
                author_id=owner_id,
                body="Initial reply",
            )
            db.add(reply)
            await db.flush()
            target_id = reply.id
        await db.commit()

    reached_commit, resume = asyncio.Event(), asyncio.Event()

    async def edit(name):
        async with postgres_race.session(name) as db:
            actor = await db.get(User, owner_id)
            if name == "first":
                commit = db.commit

                async def held_commit():
                    await db.flush()
                    reached_commit.set()
                    await asyncio.wait_for(resume.wait(), timeout=5)
                    await commit()

                monkeypatch.setattr(db, "commit", held_commit)
            try:
                if kind == "reply":
                    return await update_annotation_reply(
                        db,
                        actor,
                        workspace_id,
                        item_id,
                        annotation_id,
                        target_id,
                        AnnotationReplyUpdate(version=1, body=name),
                    )
                return await update_document_annotation(
                    db,
                    actor,
                    workspace_id,
                    item_id,
                    annotation_id,
                    AnnotationUpdate.model_validate({
                        "version": 1,
                        "page_index": 0,
                        "kind": "note",
                        "scope": "private",
                        "body": name,
                        "payload": {
                            "type": "note",
                            "rect": {"x": 1, "y": 1, "width": 1, "height": 1},
                        },
                    }),
                )
            except VersionConflict as error:
                await db.rollback()
                return error

    postgres_race.start("first", edit("first"))
    await asyncio.wait_for(reached_commit.wait(), timeout=5)
    postgres_race.start("second", edit("second"))
    try:
        await postgres_race.wait_blocked("second", "first")
    finally:
        resume.set()
    assert (await postgres_race.join("first"))["version"] == 2
    conflict = await postgres_race.join("second")
    assert isinstance(conflict, VersionConflict)
    assert conflict.current_version == 2
    async with postgres_race.session("verify") as db:
        model = PdfAnnotation if kind == "annotation" else PdfAnnotationReply
        record = await db.get(model, target_id)
        assert (record.body, record.version) == ("first", 2)
        action = "annotation.update" if kind == "annotation" else "annotation_reply.update"
        assert (
            await db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.action == action))
            == 1
        )


@pytest.mark.concurrency_case("foreign-lock-isolation")
async def test_cross_workspace_discussion_id_does_not_lock_foreign_row(postgres_sessions):
    async with postgres_sessions() as setup_db:
        first_owner = await _user(setup_db, "discussion-lock-first")
        second_owner = await _user(setup_db, "discussion-lock-second")
        first_workspace_id = fixture_workspace_id(first_owner)
        second_workspace_id = fixture_workspace_id(second_owner)
        first_item = Item(
            workspace_id=first_workspace_id,
            title="Requested Workspace Item",
            created_by=first_owner.id,
        )
        second_item = Item(
            workspace_id=second_workspace_id,
            title="Foreign Workspace Item",
            created_by=second_owner.id,
        )
        setup_db.add_all([first_item, second_item])
        await setup_db.commit()
        foreign_message = await add_discussion_message(
            setup_db,
            second_owner,
            second_workspace_id,
            second_item.id,
            "Foreign row",
        )
        first_owner_id = first_owner.id
        first_item_id = first_item.id
        foreign_message_id = foreign_message.id

    async with postgres_sessions() as requester_db:
        requester = await requester_db.get(User, first_owner_id)
        assert requester is not None
        with pytest.raises(ResourceUnavailable):
            await delete_discussion_message(
                requester_db,
                requester,
                first_workspace_id,
                first_item_id,
                foreign_message_id,
            )

        async with postgres_sessions() as foreign_db:
            locked = await foreign_db.scalar(
                select(DiscussionMessage)
                .where(DiscussionMessage.id == foreign_message_id)
                .with_for_update(nowait=True)
            )
            assert locked is not None
            await foreign_db.rollback()
        await requester_db.rollback()


@pytest.mark.concurrency_case("workspace-archive-write")
async def test_write_authorization_serializes_with_workspace_archive(
    postgres_sessions, postgres_race
):
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

    async def write_message():
        async with postgres_race.session("writer") as db:
            actor = await db.get(User, writer_id)
            assert actor is not None
            await require_workspace_action(
                db, actor, workspace_id, ResourceAction.item_discussion_create
            )
            authorized.set()
            postgres_race.note("write.authorized", actor="writer")
            await release_write.wait()
            return await add_discussion_message(db, actor, workspace_id, item_id, "Before archive")

    async def archive():
        async with postgres_race.session("archive") as db:
            actor = await db.get(User, owner_id)
            assert actor is not None
            await archive_workspace(db, actor, workspace_id)

    postgres_race.start("writer", write_message())
    await asyncio.wait_for(authorized.wait(), timeout=5)
    postgres_race.start("archive", archive())
    await postgres_race.wait_blocked("archive", "writer")
    release_write.set()
    await postgres_race.join("writer")
    await postgres_race.join("archive")

    async with postgres_sessions() as db:
        actor = await db.get(User, writer_id)
        assert actor is not None
        with pytest.raises(WorkspaceLifecycleError):
            await add_discussion_message(db, actor, workspace_id, item_id, "After archive")


@pytest.mark.concurrency_case("project-archive-write")
async def test_project_discussion_waits_for_archive_and_rechecks_state(
    postgres_sessions, postgres_race
):
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

    async with postgres_race.session("archive") as archive_db:
        project = await archive_db.scalar(
            select(Project).where(Project.id == project_id).with_for_update()
        )
        assert project is not None
        project.state = ProjectState.archived

        async def write_message():
            async with postgres_race.session("writer") as db:
                actor = await db.get(User, owner_id)
                assert actor is not None
                with pytest.raises(ProjectLifecycleError):
                    await add_project_discussion_message(
                        db, actor, workspace_id, project_id, "After archive"
                    )

        postgres_race.start("writer", write_message())
        await postgres_race.wait_blocked("writer", "archive")
        await archive_db.commit()
        await postgres_race.join("writer")


@pytest.mark.concurrency_case("workspace-archive-write")
async def test_waiting_writer_reloads_workspace_after_archive_commits(
    postgres_sessions, postgres_race
):
    async with postgres_sessions() as db:
        owner = await _user(db, "waiting-write-owner")
        workspace_id, owner_id = fixture_workspace_id(owner), owner.id

    async with postgres_race.session("archive") as governance_db:
        workspace = await governance_db.scalar(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        assert workspace is not None
        workspace.state = WorkspaceState.archived

        async def authorize_write():
            async with postgres_race.session("writer") as db:
                actor = await db.get(User, owner_id)
                assert actor is not None
                with pytest.raises(WorkspaceLifecycleError):
                    await require_workspace_action(
                        db, actor, workspace_id, ResourceAction.item_discussion_create
                    )

        postgres_race.start("writer", authorize_write())
        await postgres_race.wait_blocked("writer", "archive")
        await governance_db.commit()
        await postgres_race.join("writer")


@pytest.mark.concurrency_case("membership-identity")
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


@pytest.mark.concurrency_case("actor-revocation")
async def test_workspace_invitation_serializes_with_invitee_deactivation(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "invite-deactivate-owner")
        controller = await _user(db, "invite-deactivate-controller")
        invitee = await _user(db, "invite-deactivate-target")
        controller.role = "administrator"

        # The invitee cannot be deactivated while owning its provisioned
        # Workspace, so transfer that independent governance root first.
        invitee_workspace_id = fixture_workspace_id(invitee)
        controller_membership = WorkspaceMember(
            workspace_id=invitee_workspace_id,
            user_id=controller.id,
            role=WorkspaceRole.admin,
            invited_by=invitee.id,
        )
        db.add(controller_membership)
        await db.flush()
        await transfer_workspace_ownership(
            db, invitee, invitee_workspace_id, controller_membership.id
        )
        workspace_id = fixture_workspace_id(owner)
        owner_id, controller_id, invitee_id = owner.id, controller.id, invitee.id

    invitation_started = asyncio.Event()
    deactivation_started = asyncio.Event()

    async def invite():
        async with postgres_sessions() as db:
            actor = await db.get(User, owner_id)
            target = await db.get(User, invitee_id)
            assert actor is not None and target is not None
            invitation_started.set()
            await invite_workspace_member(
                db, actor, workspace_id, target.username, WorkspaceRole.viewer
            )
            return "invited"

    async def deactivate():
        async with postgres_sessions() as db:
            actor = await db.get(User, controller_id)
            assert actor is not None
            deactivation_started.set()
            await update_user_status(db, actor, invitee_id, active=False)
            return "deactivated"

    async with postgres_sessions() as blocker_db:
        workspace = await blocker_db.scalar(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        assert workspace is not None

        invitation_task = asyncio.create_task(invite())
        await invitation_started.wait()
        await asyncio.sleep(0.05)
        assert not invitation_task.done()

        deactivation_task = asyncio.create_task(deactivate())
        await deactivation_started.wait()
        await asyncio.sleep(0.05)
        # Invitation holds the invitee's shared User lock while waiting for the
        # Workspace, so deactivation cannot overtake it.
        assert not deactivation_task.done()

        await blocker_db.commit()
        outcomes = await asyncio.wait_for(
            asyncio.gather(invitation_task, deactivation_task), timeout=5
        )

    assert outcomes == ["invited", "deactivated"]


@pytest.mark.concurrency_case("governance-demotion")
async def test_workspace_governance_serializes_with_admin_demotion(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "governance-demotion-owner")
        governance_admin = await _user(db, "governance-demotion-target")
        controller = await _user(db, "governance-demotion-controller")
        governance_admin.role = "administrator"
        controller.role = "administrator"
        await db.commit()
        workspace_id = fixture_workspace_id(owner)
        governance_admin_id, controller_id = governance_admin.id, controller.id

    governance_started = asyncio.Event()
    demotion_started = asyncio.Event()

    async def suspend_governance():
        async with postgres_sessions() as db:
            actor = await db.get(User, governance_admin_id)
            assert actor is not None
            governance_started.set()
            await freeze_workspace_governance(db, actor, workspace_id)
            return "suspended"

    async def demote():
        async with postgres_sessions() as db:
            actor = await db.get(User, controller_id)
            assert actor is not None
            demotion_started.set()
            await change_user_role(db, actor, governance_admin_id, "member")
            return "demoted"

    async with postgres_sessions() as blocker_db:
        workspace = await blocker_db.scalar(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        assert workspace is not None

        governance_task = asyncio.create_task(suspend_governance())
        await governance_started.wait()
        await asyncio.sleep(0.05)
        assert not governance_task.done()

        demotion_task = asyncio.create_task(demote())
        await demotion_started.wait()
        await asyncio.sleep(0.05)
        # Governance holds current administrator authority under a shared User
        # lock, so revocation cannot commit ahead of the operation.
        assert not demotion_task.done()

        await blocker_db.commit()
        outcomes = await asyncio.wait_for(asyncio.gather(governance_task, demotion_task), timeout=5)

    assert outcomes == ["suspended", "demoted"]


@pytest.mark.concurrency_case("governance-demotion")
async def test_cross_admin_demotion_locks_users_in_stable_order(postgres_sessions):
    async with postgres_sessions() as db:
        first = await _user(db, "cross-demotion-first")
        second = await _user(db, "cross-demotion-second")
        first.role = "administrator"
        second.role = "administrator"
        await db.commit()
        first_id, second_id = first.id, second.id

    gate = asyncio.Event()
    ready = 0
    ready_lock = asyncio.Lock()

    async def demote(actor_id: str, target_id: str) -> str:
        nonlocal ready
        async with postgres_sessions() as db:
            actor = await db.get(User, actor_id)
            assert actor is not None
            async with ready_lock:
                ready += 1
                if ready == 2:
                    gate.set()
            await gate.wait()
            try:
                await change_user_role(db, actor, target_id, "member")
            except ResourceUnavailable:
                await db.rollback()
                return "denied"
            return "demoted"

    outcomes = await asyncio.wait_for(
        asyncio.gather(
            demote(first_id, second_id),
            demote(second_id, first_id),
        ),
        timeout=5,
    )
    assert sorted(outcomes) == ["demoted", "denied"]


@pytest.mark.concurrency_case("actor-revocation")
async def test_password_hashing_does_not_hold_the_user_authorization_lock(
    postgres_sessions,
    monkeypatch,
):
    async with postgres_sessions() as db:
        administrator = await _user(db, "password-change-admin")
        administrator.role = "administrator"
        user = User(
            username=f"password-change-target-{uuid4()}",
            password_hash="verified-hash",
        )
        db.add(user)
        await db.commit()
        administrator_id, user_id = administrator.id, user.id

    hashing_started = asyncio.Event()
    release_hashing = asyncio.Event()

    async def verify_password(_encoded: str, _password: str) -> bool:
        await asyncio.sleep(0)
        return True

    async def hash_password(_password: str) -> str:
        hashing_started.set()
        await release_hashing.wait()
        return "replacement-hash"

    monkeypatch.setattr("quirebase.accounts.authentication.verify_password_async", verify_password)
    monkeypatch.setattr("quirebase.accounts.authentication.hash_password_async", hash_password)

    async with postgres_sessions() as password_db:
        actor = await password_db.get(User, user_id)
        assert actor is not None
        password_task = asyncio.create_task(
            change_own_password(password_db, actor, "current-password", "replacement-password")
        )
        await hashing_started.wait()
        try:
            async with postgres_sessions() as admin_db:
                administrator = await admin_db.get(User, administrator_id)
                assert administrator is not None
                await asyncio.wait_for(
                    update_user_status(admin_db, administrator, user_id, active=False),
                    timeout=2,
                )
        finally:
            release_hashing.set()

        outcome = await asyncio.wait_for(
            asyncio.gather(password_task, return_exceptions=True), timeout=5
        )
    assert len(outcome) == 1
    assert isinstance(outcome[0], ResourceUnavailable)


@pytest.mark.concurrency_case("governance-demotion")
async def test_admin_password_hashing_precedes_final_locked_reauthorization(
    postgres_sessions,
    monkeypatch,
):
    async with postgres_sessions() as db:
        controller = await _user(db, "password-reset-controller")
        resetter = await _user(db, "password-reset-actor")
        controller.role = "administrator"
        resetter.role = "administrator"
        target = User(
            username=f"password-reset-target-{uuid4()}",
            password_hash="old-hash",
        )
        db.add(target)
        await db.commit()
        controller_id, resetter_id, target_id = controller.id, resetter.id, target.id

    hashing_started = asyncio.Event()
    release_hashing = asyncio.Event()

    async def hash_password(_password: str) -> str:
        hashing_started.set()
        await release_hashing.wait()
        return "replacement-hash"

    monkeypatch.setattr("quirebase.accounts.administration.hash_password_async", hash_password)

    async with postgres_sessions() as reset_db:
        resetter = await reset_db.get(User, resetter_id)
        assert resetter is not None
        reset_task = asyncio.create_task(
            reset_user_password(reset_db, resetter, target_id, "replacement-password")
        )
        await hashing_started.wait()
        try:
            async with postgres_sessions() as controller_db:
                controller = await controller_db.get(User, controller_id)
                assert controller is not None
                await asyncio.wait_for(
                    change_user_role(controller_db, controller, resetter_id, "member"),
                    timeout=2,
                )
        finally:
            release_hashing.set()

        outcome = await asyncio.wait_for(
            asyncio.gather(reset_task, return_exceptions=True), timeout=5
        )
    assert len(outcome) == 1
    assert isinstance(outcome[0], ResourceUnavailable)


@pytest.mark.concurrency_case("ownership-transfer")
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
        current_owner_id = await db.scalar(
            select(WorkspaceMember.user_id).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == WorkspaceRole.owner,
                WorkspaceMember.terminated_at.is_(None),
            )
        )
        assert current_owner_id in {first.id, second.id}


@pytest.mark.concurrency_case("actor-revocation")
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
        assert (
            await db.scalar(
                select(WorkspaceMember.user_id).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.role == WorkspaceRole.owner,
                    WorkspaceMember.terminated_at.is_(None),
                )
            )
            == target.id
        )
        assert target.active is True


@pytest.mark.concurrency_case("actor-revocation")
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


@pytest.mark.concurrency_case("upload-finalization")
@pytest.mark.parametrize("role", [None, AttachmentRole.graphical_abstract])
async def test_upload_finalizers_for_different_items_share_workspace_guard(
    postgres_sessions, postgres_race, role
):
    async with postgres_sessions() as db:
        actor = await _user(db, "parallel-upload-owner")
        workspace_id, actor_id = fixture_workspace_id(actor), actor.id
        items = [
            Item(workspace_id=workspace_id, title=f"Parallel upload {i}", created_by=actor_id)
            for i in range(2)
        ]
        db.add_all(items)
        await db.commit()
        item_ids = [item.id for item in items]

    async def finalize_second():
        async with postgres_race.session("second") as db:
            await _lock_upload_authority(db, actor_id, workspace_id, item_ids[1], role=role)
            await db.commit()
            return "finalized"

    async def archive():
        async with postgres_race.session("archive") as db:
            actor = await db.get(User, actor_id)
            await archive_workspace(db, actor, workspace_id)

    async with postgres_race.session("first") as db:
        await _lock_upload_authority(db, actor_id, workspace_id, item_ids[0], role=role)
        postgres_race.start("second", finalize_second())
        # A second Item can finalize while the first transaction remains open.
        assert await postgres_race.join("second") == "finalized"
        postgres_race.start("archive", archive())
        await postgres_race.wait_blocked("archive", "first")
        await db.commit()
        await postgres_race.join("archive")

    async with postgres_race.session("rejected") as db:
        with pytest.raises(ValueError, match="no longer writable"):
            await _lock_upload_authority(db, actor_id, workspace_id, item_ids[1], role=role)


@pytest.mark.concurrency_case("actor-revocation")
async def test_import_confirmation_and_deactivation_follow_user_workspace_lock_order(
    postgres_sessions,
    postgres_search_tables,
    postgres_race,
):
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
            records=[{"title": "Confirmed without a deadlock"}],
            errors=[],
            status="ready",
        )
        db.add(batch)
        await db.commit()
        administrator_id, actor_id, batch_id = administrator.id, actor.id, batch.id

    async def confirm_import() -> str:
        async with postgres_race.session("confirm") as db:
            actor = await db.get(User, actor_id)
            assert actor is not None
            await commit_import_batch(db, actor, workspace_id, batch_id)
            return "confirmed"

    async def deactivate_actor() -> str:
        async with postgres_race.session("deactivate") as db:
            administrator = await db.get(User, administrator_id)
            assert administrator is not None
            await update_user_status(db, administrator, actor_id, active=False)
            return "deactivated"

    async with postgres_race.session("blocker") as blocker_db:
        workspace = await blocker_db.scalar(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )
        assert workspace is not None

        postgres_race.start("confirm", confirm_import())
        await postgres_race.wait_blocked("confirm", "blocker")
        postgres_race.start("deactivate", deactivate_actor())
        await postgres_race.wait_blocked("deactivate", "confirm")

        await blocker_db.commit()
        outcomes = [await postgres_race.join("confirm"), await postgres_race.join("deactivate")]

    assert outcomes == ["confirmed", "deactivated"]
    async with postgres_race.session("verify") as db:
        administrator = await db.get(User, administrator_id)
        items, total, *_ = await search_library(db, administrator, workspace_id, q="Confirmed")
        assert total == 1 and items[0].title == "Confirmed without a deadlock"


@pytest.mark.concurrency_case("participation-recheck")
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


@pytest.mark.concurrency_case("participation-recheck")
@pytest.mark.parametrize("first", ["settings", "add"])
async def test_project_participation_add_races_switch_to_workspace_mode(
    postgres_sessions, postgres_race, monkeypatch, first
):
    async with postgres_sessions() as db:
        owner = await _user(db, "participation-owner")
        target = await _user(db, "participation-target")
        workspace_id = fixture_workspace_id(owner)
        owner_id, target_id, target_username = owner.id, target.id, target.username
        db.add(
            WorkspaceMember(
                workspace_id=workspace_id,
                user_id=target_id,
                role=WorkspaceRole.editor,
                invited_by=owner_id,
            )
        )
        await db.commit()
        project = await create_project(
            db, owner, workspace_id, "Concurrent participation", ProjectParticipation.managed
        )
        project_id = project.id

    ready_to_commit = asyncio.Event()
    release_commit = asyncio.Event()

    async def mutate(operation):
        async with postgres_race.session(operation) as db:
            actor = await db.get(User, owner_id)
            if operation == first:
                commit = db.commit

                async def held_commit():
                    await db.flush()
                    ready_to_commit.set()
                    await release_commit.wait()
                    await commit()

                monkeypatch.setattr(db, "commit", held_commit)
            try:
                if operation == "settings":
                    await set_project_participation(
                        db, actor, workspace_id, project_id, ProjectParticipation.workspace
                    )
                else:
                    await add_project_participant(
                        db, actor, workspace_id, project_id, target_username
                    )
                return "committed"
            except ProjectParticipationConflict:
                await db.rollback()
                return "rejected"

    second = "add" if first == "settings" else "settings"
    postgres_race.start(first, mutate(first))
    await asyncio.wait_for(ready_to_commit.wait(), timeout=5)
    postgres_race.start(second, mutate(second))
    try:
        await postgres_race.wait_blocked(second, first)
    finally:
        release_commit.set()
    assert await postgres_race.join(first) == "committed"
    assert await postgres_race.join(second) == ("rejected" if first == "settings" else "committed")

    async with postgres_sessions() as db:
        project = await db.get(Project, project_id)
        assert project.participation is ProjectParticipation.workspace
        assert (
            await db.scalar(
                select(ProjectParticipant.id).where(ProjectParticipant.project_id == project_id)
            )
            is None
        )
        add_events = await db.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.project_id == project_id, AuditEvent.action == "project.participant.add"
            )
        )
        assert add_events == int(first == "add")
        assert (
            await db.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.project_id == project_id,
                    AuditEvent.action == "project.settings.update",
                )
            )
            == 1
        )


@pytest.mark.concurrency_case("annotation-recheck")
async def test_reply_create_waits_for_annotation_moderation_and_rechecks(postgres_sessions):
    async with postgres_sessions() as db:
        (
            workspace_id,
            owner_id,
            item_id,
            _project_id,
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


@pytest.mark.concurrency_case("reply-root-delete")
async def test_reply_create_races_archived_workspace_root_deletion(
    postgres_sessions, postgres_race
):
    async with postgres_sessions() as db:
        (
            workspace_id,
            owner_id,
            item_id,
            _project_id,
            _assignment_id,
            annotation_id,
        ) = await _project_annotation_context(db, "reply-workspace-delete")
        await archive_workspace(db, await db.get(User, owner_id), workspace_id)

    async with postgres_race.session("delete") as delete_db:
        workspace = await delete_db.scalar(
            select(Workspace).where(Workspace.id == workspace_id).with_for_update()
        )

        async def reply():
            async with postgres_race.session("reply") as reply_db:
                actor = await reply_db.get(User, owner_id)
                try:
                    await create_annotation_reply(
                        reply_db,
                        actor,
                        workspace_id,
                        item_id,
                        annotation_id,
                        AnnotationReplyCreate(id=uuid4(), body="Concurrent reply"),
                    )
                except WorkspaceUnavailable:
                    await reply_db.rollback()
                    return "rejected"
                return "committed"

        postgres_race.start("reply", reply())
        await postgres_race.wait_blocked("reply", "delete")
        await delete_db.delete(workspace)
        await delete_db.flush()
        await delete_db.commit()
        assert await postgres_race.join("reply") == "rejected"


@pytest.mark.concurrency_case("annotation-recheck")
async def test_reply_create_waits_for_project_item_detachment_and_rechecks(postgres_sessions):
    async with postgres_sessions() as db:
        (
            workspace_id,
            owner_id,
            item_id,
            _project_id,
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


@pytest.mark.concurrency_case("annotation-recheck")
async def test_annotation_scope_update_waits_for_project_item_detachment_and_rechecks(
    postgres_sessions,
):
    async with postgres_sessions() as db:
        (
            workspace_id,
            owner_id,
            item_id,
            project_id,
            assignment_id,
            annotation_id,
        ) = await _project_annotation_context(
            db,
            "annotation-scope-detachment",
            annotation_scope=AnnotationScope.private,
        )

    async with postgres_sessions() as detach_db:
        assignment = await detach_db.scalar(
            select(ProjectItem).where(ProjectItem.id == assignment_id).with_for_update()
        )
        assert assignment is not None
        await detach_db.delete(assignment)
        await detach_db.flush()

        started = asyncio.Event()

        async def update_scope() -> str:
            async with postgres_sessions() as db:
                actor = await db.get(User, owner_id)
                assert actor is not None
                started.set()
                try:
                    await update_document_annotation(
                        db,
                        actor,
                        workspace_id,
                        item_id,
                        annotation_id,
                        AnnotationUpdate.model_validate({
                            "version": 1,
                            "page_index": 0,
                            "kind": "note",
                            "scope": "project",
                            "project_id": project_id,
                            "body": "Moved to Project scope",
                            "payload": {
                                "type": "note",
                                "rect": {"x": 1, "y": 1, "width": 1, "height": 1},
                            },
                        }),
                    )
                except ResourceUnavailable:
                    await db.rollback()
                    return "rejected"
                return "committed"

        update_task = asyncio.create_task(update_scope())
        try:
            await started.wait()
            await asyncio.sleep(0.05)
            assert not update_task.done()
        finally:
            await detach_db.commit()
        assert await asyncio.wait_for(update_task, timeout=5) == "rejected"

    async with postgres_sessions() as db:
        annotation = await db.get(PdfAnnotation, annotation_id)
        assert annotation is not None
        assert annotation.scope is AnnotationScope.private
        assert annotation.project_item_id is None
        assert annotation.version == 1
        assert await db.get(ProjectItem, assignment_id) is None


@pytest.mark.concurrency_case("assignment-item-delete")
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


@pytest.mark.concurrency_case("participation-recheck")
async def test_project_join_uses_shared_workspace_guard(postgres_sessions):
    async with postgres_sessions() as db:
        owner = await _user(db, "shared-join-owner")
        participant = await _user(db, "shared-join-participant")
        workspace_id = fixture_workspace_id(owner)
        db.add(
            WorkspaceMember(
                workspace_id=workspace_id,
                user_id=participant.id,
                role=WorkspaceRole.editor,
                invited_by=owner.id,
            )
        )
        await db.commit()
        project = await create_project(
            db, owner, workspace_id, "Shared guard join", ProjectParticipation.open
        )
        project_id = project.id
        participant_id = participant.id

    async with postgres_sessions() as blocker:
        await blocker.scalar(
            select(Workspace.id).where(Workspace.id == workspace_id).with_for_update(read=True)
        )
        async with postgres_sessions() as join_db:
            actor = await join_db.get(User, participant_id)
            assert actor is not None
            joined = await asyncio.wait_for(
                join_project(join_db, actor, workspace_id, project_id), timeout=2
            )
            assert joined.user_id == participant_id
        await blocker.rollback()


@pytest.mark.concurrency_case("participation-recheck")
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
            db, owner, workspace_id, "Open join race", ProjectParticipation.open
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
            select(ProjectParticipant).where(
                ProjectParticipant.workspace_id == workspace_id,
                ProjectParticipant.project_id == project_id,
                ProjectParticipant.user_id == target_id,
            )
        )
        if "rejected" in outcomes:
            assert participant is None
        else:
            assert participant is not None


@pytest.mark.concurrency_case("relation-idempotency")
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


@pytest.mark.concurrency_case("relation-idempotency")
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
        assert (
            await db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.action == "tag.add"))
            == 1
        )


@pytest.mark.concurrency_case("relation-idempotency")
async def test_single_tag_add_reports_conflict_if_skipped_link_is_removed_before_result_read(
    postgres_sessions, postgres_race, monkeypatch
):
    async with postgres_sessions() as db:
        actor = await _user(db, "single-tag-remove-owner")
        workspace_id, actor_id = fixture_workspace_id(actor), actor.id
        item = Item(workspace_id=workspace_id, title="Removed duplicate", created_by=actor_id)
        tag = Tag(workspace_id=workspace_id, name="Existing tag", created_by=actor_id)
        db.add_all([item, tag])
        await db.commit()
        item_id, tag_id = item.id, tag.id
        await add_existing_tag_to_item(db, actor, workspace_id, item_id, tag_id)

    rereading, resume = asyncio.Event(), asyncio.Event()
    get_one_or_none = ItemTagRepository.get_one_or_none

    async def paused_read(self, *args, **kwargs):
        rereading.set()
        await asyncio.wait_for(resume.wait(), timeout=5)
        return await get_one_or_none(self, *args, **kwargs)

    monkeypatch.setattr(ItemTagRepository, "get_one_or_none", paused_read)

    async def add():
        async with postgres_race.session("add") as db:
            actor = await db.get(User, actor_id)
            try:
                await add_existing_tag_to_item(db, actor, workspace_id, item_id, tag_id)
            except TagConflict:
                await db.rollback()
                return "conflict"
            return "added"

    postgres_race.start("add", add())
    await asyncio.wait_for(rereading.wait(), timeout=5)
    try:
        async with postgres_race.session("remove") as db:
            actor = await db.get(User, actor_id)
            await remove_tag_from_item(db, actor, workspace_id, item_id, tag_id)
    finally:
        resume.set()
    assert await postgres_race.join("add") == "conflict"
    async with postgres_race.session("verify") as db:
        assert await db.get(ItemTag, (item_id, tag_id)) is None
        assert (
            await db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.action == "tag.add"))
            == 1
        )


@pytest.mark.concurrency_case("relation-idempotency")
@pytest.mark.parametrize("kind", ["tag", "project"])
async def test_association_batch_skips_a_competing_insert_without_losing_other_links(
    postgres_sessions, postgres_race, monkeypatch, kind
):
    async with postgres_sessions() as db:
        actor = await _user(db, f"{kind}-batch-overlap")
        workspace_id, actor_id = fixture_workspace_id(actor), actor.id
        items = [
            Item(workspace_id=workspace_id, title=f"Overlap {index}", created_by=actor_id)
            for index in range(2)
        ]
        root = (
            Tag(workspace_id=workspace_id, name="Overlap tag", created_by=actor_id)
            if kind == "tag"
            else Project(workspace_id=workspace_id, name="Overlap project", created_by=actor_id)
        )
        db.add_all([*items, root])
        await db.commit()
        item_ids, root_id = [item.id for item in items], root.id

    model = ItemTag if kind == "tag" else ProjectItem
    checked, resume = asyncio.Event(), asyncio.Event()

    async def batch():
        async with postgres_race.session("batch") as db:
            scalars = db.scalars

            async def paused_scalars(statement, *args, **kwargs):
                if (
                    statement.is_insert
                    and not checked.is_set()
                    and statement.table.name == model.__tablename__
                ):
                    checked.set()
                    postgres_race.note("association.before_insert", actor="batch")
                    await asyncio.wait_for(resume.wait(), timeout=5)
                return await scalars(statement, *args, **kwargs)

            monkeypatch.setattr(db, "scalars", paused_scalars)
            actor = await db.get(User, actor_id)
            if kind == "tag":
                return await apply_bulk_item_action(
                    db, actor, workspace_id, item_ids, "add_tag", tag_name="Overlap tag"
                )
            inserted = await add_items_to_project(db, actor, workspace_id, root_id, item_ids)
            await db.commit()
            return inserted

    async def single():
        async with postgres_race.session("single") as db:
            actor = await db.get(User, actor_id)
            if kind == "tag":
                await add_existing_tag_to_item(db, actor, workspace_id, item_ids[0], root_id)
            else:
                await add_item_to_project(db, actor, workspace_id, root_id, item_ids[0])

    postgres_race.start("batch", batch())
    await asyncio.wait_for(checked.wait(), timeout=5)
    try:
        postgres_race.start("single", single())
        await postgres_race.join("single")
    finally:
        resume.set()
    inserted = await postgres_race.join("batch")
    if kind == "project":
        assert inserted == 1
    async with postgres_race.session("verify") as db:
        assert set(await db.scalars(select(model.item_id))) == set(item_ids)
        action = "tag.add" if kind == "tag" else "project.item.add"
        assert (
            await db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.action == action))
            == 1
        )


@pytest.mark.concurrency_case("relation-idempotency")
async def test_bulk_tag_add_does_not_resurrect_a_link_removed_after_conflict_skip(
    postgres_sessions, postgres_race, monkeypatch
):
    async with postgres_sessions() as db:
        actor = await _user(db, "bulk-tag-remove-owner")
        workspace_id, actor_id = fixture_workspace_id(actor), actor.id
        items = [
            Item(workspace_id=workspace_id, title=f"Tag race {i}", created_by=actor_id)
            for i in range(2)
        ]
        tag = Tag(workspace_id=workspace_id, name="Disappearing duplicate", created_by=actor_id)
        db.add_all([*items, tag])
        await db.commit()
        item_ids, tag_id = [item.id for item in items], tag.id
        await add_existing_tag_to_item(db, actor, workspace_id, item_ids[0], tag_id)

    inserted, resume = asyncio.Event(), asyncio.Event()

    async def batch():
        async with postgres_race.session("batch") as db:
            scalars = db.scalars

            async def paused_scalars(statement, *args, **kwargs):
                result = await scalars(statement, *args, **kwargs)
                if statement.is_insert and statement.table.name == ItemTag.__tablename__:
                    inserted.set()
                    postgres_race.note("association.skipped_duplicate", actor="batch")
                    await asyncio.wait_for(resume.wait(), timeout=5)
                return result

            monkeypatch.setattr(db, "scalars", paused_scalars)
            actor = await db.get(User, actor_id)
            await apply_bulk_item_action(
                db, actor, workspace_id, item_ids, "add_tag", tag_name=tag.name
            )

    postgres_race.start("batch", batch())
    await asyncio.wait_for(inserted.wait(), timeout=5)
    try:
        async with postgres_race.session("remove") as db:
            actor = await db.get(User, actor_id)
            await remove_tag_from_item(db, actor, workspace_id, item_ids[0], tag_id)
    finally:
        resume.set()
    await postgres_race.join("batch")

    async with postgres_race.session("verify") as db:
        assert set(await db.scalars(select(ItemTag.item_id))) == {item_ids[1]}
        assert (
            await db.scalar(
                select(func.count(AuditEvent.id)).where(AuditEvent.action == "library.bulk.add_tag")
            )
            == 1
        )


@pytest.mark.concurrency_case("import-replay")
@pytest.mark.parametrize("first", ["first", "second"], ids=["first-starts", "second-starts"])
async def test_concurrent_import_confirmation_and_response_loss_replay(
    postgres_sessions, postgres_search_tables, postgres_race, first
):
    async with postgres_sessions() as db:
        owner = await _user(db, "import-replay")
        owner.role = "administrator"
        await db.commit()
        workspace_id, owner_id = fixture_workspace_id(owner), owner.id
        batch, records, errors = await stage_import_batch(
            db,
            owner,
            workspace_id,
            b"@article{a, title={Alphaconfirm}}\n@article{b, title={Betaconfirm}}",
            "bibtex",
        )
        assert len(records) == 2 and not errors
        batch_id = batch.id

    async def confirm(name):
        async with postgres_race.session(name) as db:
            return await commit_import_batch(
                db, await db.get(User, owner_id), workspace_id, batch_id
            )

    async with postgres_race.session("blocker") as db:
        await db.scalar(select(ImportBatch).where(ImportBatch.id == batch_id).with_for_update())
        second = "second" if first == "first" else "first"
        for name in (first, second):
            postgres_race.start(name, confirm(name))
            # PostgreSQL queues the second contender behind the first one's
            # tuple lock, while the first waits for the blocker's transaction.
            await postgres_race.wait_blocked(name, "blocker" if name == first else first)
        await db.commit()
    first_ids = await postgres_race.join(first)
    second_ids = await postgres_race.join(second)
    assert len(first_ids) == 2 and first_ids == second_ids

    # The client loses the committed response, then retries on a fresh Session.
    async with postgres_race.session("replay") as db:
        owner = await db.get(User, owner_id)
        assert await commit_import_batch(db, owner, workspace_id, batch_id) == first_ids
        items, total, *_ = await search_library(db, owner, workspace_id)
        assert total == 2 and {item.id for item in items} == set(first_ids)
        events, total = await query_events(db, owner, action="bibliography.import")
        assert total == 2 and {event.target_id for event in events} == {
            str(item_id) for item_id in first_ids
        }
        items, total, *_ = await search_library(db, owner, workspace_id, q="Alphaconfirm")
        assert total == 1 and items[0].id in first_ids


@pytest.mark.concurrency_case("metadata-version")
@pytest.mark.parametrize("winner", ["Alpharace", "Betarace"], ids=["alpha-first", "beta-first"])
async def test_concurrent_metadata_replacements_reject_stale_version(
    postgres_sessions, postgres_search_tables, postgres_race, winner
):
    loser = "Betarace" if winner == "Alpharace" else "Alpharace"
    async with postgres_sessions() as db:
        owner = await _user(db, "metadata-cas")
        owner.role = "administrator"
        item = Item(workspace_id=fixture_workspace_id(owner), title="Original", created_by=owner.id)
        db.add(item)
        await db.commit()
        workspace_id, owner_id, item_id = fixture_workspace_id(owner), owner.id, item.id

    async def replace_second():
        async with postgres_race.session("second") as db:
            actor = await db.get(User, owner_id)
            with pytest.raises(VersionConflict) as conflict:
                await revise_item_metadata(db, actor, workspace_id, item_id, 1, ItemMetadata(loser))
            assert conflict.value.current_version == 2

    async with postgres_race.session("first") as db:
        actor = await db.get(User, owner_id)
        await require_workspace_action(db, actor, workspace_id, ResourceAction.item_update)
        await db.scalar(select(Item).where(Item.id == item_id).with_for_update())
        postgres_race.start("second", replace_second())
        await postgres_race.wait_blocked("second", "first")
        result = await revise_item_metadata(
            db, actor, workspace_id, item_id, 1, ItemMetadata(winner)
        )
        assert result.version == 2
        await postgres_race.join("second")

    async with postgres_race.session("verify") as db:
        actor = await db.get(User, owner_id)
        context = await resolve_workspace_context(db, actor, workspace_id)
        view = await open_item_section(db, context, item_id, ItemSection.metadata)
        assert isinstance(view, ItemMetadataData)
        assert view.metadata.title == winner and view.item.version == 2
        items, total, *_ = await search_library(db, actor, workspace_id, q=winner)
        assert total == 1 and items[0].id == item_id
        assert (await search_library(db, actor, workspace_id, q=loser))[1] == 0
        events, total = await query_events(db, actor, action="item.update")
        assert total == 1 and events[0].target_id == str(item_id)


@pytest.mark.concurrency_case("settings-install")
async def test_concurrent_setting_upserts_preserve_whole_batch(postgres_sessions, postgres_race):
    async with postgres_sessions() as db:
        first = User(username="settings-first", password_hash="unused", role="administrator")
        second = User(username="settings-second", password_hash="unused", role="administrator")
        db.add_all([first, second, SystemSetting(key="session_days", value="30")])
        await db.commit()
        first_id, second_id = first.id, second.id

    async def install_second():
        async with postgres_race.session("second") as db:
            actor = await db.get(User, second_id)
            await update_runtime_settings(
                db,
                actor,
                {
                    "metadata_contact_email": "second@example.org",
                    "ncbi_api_key": "second-key",
                    "session_days": 60,
                },
            )

    async with postgres_race.session("first") as db:
        await RuntimeSettingsService(db).store(
            first_id, {"metadata_contact_email": "first@example.org", "session_days": 45}
        )
        postgres_race.start("second", install_second())
        await postgres_race.wait_blocked("second", "first")
        await db.commit()
        await postgres_race.join("second")

    async with postgres_race.session("verify") as db:
        rows = {record.key: record for record in await RuntimeSettingsService(db).get_many()}
        assert {key: record.value for key, record in rows.items()} == {
            "metadata_contact_email": "second@example.org",
            "ncbi_api_key": "second-key",
            "session_days": "60",
        }
        assert {record.updated_by for record in rows.values()} == {second_id}
        actor = await db.get(User, second_id)
        events, total = await query_events(db, actor, action="system.settings_update")
        assert total == 1 and events[0].actor_id == second_id


@pytest.mark.concurrency_case("citation-style-install")
async def test_concurrent_citation_style_install_translates_unique_race_and_keeps_session_usable(
    postgres_sessions, postgres_race
):
    from inquiro.bibliography import builtin_style_xml

    xml = builtin_style_xml("apa")
    assert xml is not None
    async with postgres_sessions() as db:
        owner = await _user(db, "citation-installer")
        actor_id, workspace_id = owner.id, fixture_workspace_id(owner)

    async def install_second():
        async with postgres_race.session("second") as db:
            actor = await db.get(User, actor_id)
            with pytest.raises(ValidationFailure, match="already exists"):
                await create_custom_citation_style(db, actor, workspace_id, " Shared ", xml)
            # A uniqueness conflict rolls back only its savepoint.
            await create_custom_citation_style(db, actor, workspace_id, "Distinct", xml)

    async with postgres_race.session("first") as db:
        await CitationStyleService(db).install(workspace_id, actor_id, "Shared", xml)
        postgres_race.start("second", install_second())
        await postgres_race.wait_blocked("second", "first")
        await db.commit()
        await postgres_race.join("second")

    async with postgres_race.session("verify") as db:
        names = set(
            await db.scalars(
                select(CitationStyle.name).where(CitationStyle.workspace_id == workspace_id)
            )
        )
        assert names == {"Shared", "Distinct"}


@pytest.mark.concurrency_case("author-install")
async def test_concurrent_author_batches_recover_conflicts_and_keep_missing_identities(
    postgres_sessions, postgres_race
):
    async def install_second():
        async with postgres_race.session("second") as db:
            resolved = await AuthorService(db).resolve_many([
                ("Shared", "Author"),
                ("Onlysecond", None),
                ("SHARED", "AUTHOR"),
            ])
            await db.commit()
            return {key: author.id for key, author in resolved.items()}

    async with postgres_race.session("first") as db:
        first = await AuthorService(db).resolve_many([("Shared", "Author"), ("Onlyfirst", None)])
        shared_id = first["shared\x1fauthor"].id
        postgres_race.start("second", install_second())
        await postgres_race.wait_blocked("second", "first")
        await db.commit()
        second = await postgres_race.join("second")
        assert second["shared\x1fauthor"] == shared_id
        assert "onlysecond\x1f" in second

    async with postgres_race.session("verify") as db:
        assert set(await db.scalars(select(Author.identity_key))) == {
            "shared\x1fauthor",
            "onlyfirst\x1f",
            "onlysecond\x1f",
        }


@pytest.mark.concurrency_case("participation-recheck")
@pytest.mark.parametrize("operation", ["join", "leave", "add", "remove"])
async def test_participation_guards_preserve_independent_writes_and_revocation(
    postgres_sessions, postgres_race, operation
):
    async with postgres_sessions() as db:
        owner = await _user(db, "participant-guards-owner")
        target = await _user(db, "participant-guards-target")
        workspace_id = fixture_workspace_id(owner)
        db.add(
            WorkspaceMember(workspace_id=workspace_id, user_id=target.id, role=WorkspaceRole.viewer)
        )
        await db.commit()
        mode = (
            ProjectParticipation.managed
            if operation in {"add", "remove"}
            else ProjectParticipation.open
        )
        project = await create_project(db, owner, workspace_id, "Guarded participation", mode)
        if operation == "leave":
            await join_project(db, target, workspace_id, project.id)
        elif operation == "remove":
            await add_project_participant(db, owner, workspace_id, project.id, target.username)
        project_id, owner_id, target_id, username = project.id, owner.id, target.id, target.username

    async def mutate():
        async with postgres_race.session("mutation") as db:
            actor = await db.get(User, owner_id if operation in {"add", "remove"} else target_id)
            if operation == "join":
                await join_project(db, actor, workspace_id, project_id)
            elif operation == "leave":
                await leave_project(db, actor, workspace_id, project_id)
            elif operation == "add":
                await add_project_participant(db, actor, workspace_id, project_id, username)
            else:
                await remove_project_participant(db, actor, workspace_id, project_id, target_id)
            return "committed"

    async with postgres_race.session("reader") as db:
        await db.scalar(
            select(Project.id).where(Project.id == project_id).with_for_update(read=True)
        )
        postgres_race.start("mutation", mutate())
        if operation == "remove":
            await postgres_race.wait_blocked("mutation", "reader")
            await db.rollback()
        assert await postgres_race.join("mutation") == "committed"
        await db.rollback()

    async with postgres_sessions() as db:
        participant_id = await db.scalar(
            select(ProjectParticipant.id).where(
                ProjectParticipant.project_id == project_id, ProjectParticipant.user_id == target_id
            )
        )
        assert (participant_id is not None) == (operation in {"join", "add"})


@pytest.mark.concurrency_case("relation-idempotency")
@pytest.mark.parametrize("operation", ["join", "add", "leave"])
async def test_duplicate_participation_commands_have_one_audit_effect(
    postgres_sessions, postgres_race, operation
):
    async with postgres_sessions() as db:
        owner = await _user(db, "atomic-participant-owner")
        target = await _user(db, "atomic-participant-target")
        workspace_id = fixture_workspace_id(owner)
        db.add(
            WorkspaceMember(workspace_id=workspace_id, user_id=target.id, role=WorkspaceRole.viewer)
        )
        await db.commit()
        mode = ProjectParticipation.managed if operation == "add" else ProjectParticipation.open
        project = await create_project(db, owner, workspace_id, "Atomic participation", mode)
        if operation == "leave":
            await join_project(db, target, workspace_id, project.id)
        project_id, owner_id, target_id, username = project.id, owner.id, target.id, target.username

    reached_commit, release_commit = asyncio.Event(), asyncio.Event()

    async def mutate(name):
        async with postgres_race.session(name) as db:
            actor = await db.get(User, owner_id if operation == "add" else target_id)
            if name == "winner":
                commit = db.commit

                async def held_commit():
                    reached_commit.set()
                    await release_commit.wait()
                    await commit()

                db.commit = held_commit
            if operation == "join":
                return (await join_project(db, actor, workspace_id, project_id)).id
            if operation == "add":
                return await add_project_participant(db, actor, workspace_id, project_id, username)
            return await leave_project(db, actor, workspace_id, project_id)

    postgres_race.start("winner", mutate("winner"))
    await asyncio.wait_for(reached_commit.wait(), timeout=5)
    postgres_race.start("loser", mutate("loser"))
    try:
        await postgres_race.wait_blocked("loser", "winner")
    finally:
        release_commit.set()
    assert await postgres_race.join("winner") == await postgres_race.join("loser")
    async with postgres_sessions() as db:
        count = await db.scalar(
            select(func.count(ProjectParticipant.id)).where(
                ProjectParticipant.project_id == project_id, ProjectParticipant.user_id == target_id
            )
        )
        assert count == (0 if operation == "leave" else 1)
        events = await db.scalar(
            select(func.count(AuditEvent.id)).where(
                AuditEvent.project_id == project_id,
                AuditEvent.action == f"project.participant.{operation}",
            )
        )
        assert events == 1


@pytest.mark.concurrency_case("participation-recheck")
async def test_open_join_reports_conflict_when_leave_wins_before_existing_row_reread(
    postgres_sessions, postgres_race
):
    async with postgres_sessions() as db:
        owner = await _user(db, "join-leave-owner")
        target = await _user(db, "join-leave-target")
        workspace_id = fixture_workspace_id(owner)
        db.add(
            WorkspaceMember(workspace_id=workspace_id, user_id=target.id, role=WorkspaceRole.viewer)
        )
        await db.commit()
        project = await create_project(
            db, owner, workspace_id, "Opposing selections", ProjectParticipation.open
        )
        selection = await join_project(db, target, workspace_id, project.id)
        project_id, target_id, old_selection_id = project.id, target.id, selection.id

    rereading, resume = asyncio.Event(), asyncio.Event()

    async def rejoin():
        async with postgres_race.session("rejoin") as db:
            scalar = db.scalar

            async def paused_scalar(statement, *args, **kwargs):
                if (
                    statement.is_select
                    and not rereading.is_set()
                    and statement.column_descriptions[0].get("entity") is ProjectParticipant
                ):
                    rereading.set()
                    await resume.wait()
                return await scalar(statement, *args, **kwargs)

            db.scalar = paused_scalar
            actor = await db.get(User, target_id)
            try:
                await join_project(db, actor, workspace_id, project_id)
            except ProjectParticipationConflict:
                await db.rollback()
                return "conflict"
            return "joined"

    postgres_race.start("rejoin", rejoin())
    await asyncio.wait_for(rereading.wait(), timeout=5)
    try:
        async with postgres_race.session("leave") as db:
            actor = await db.get(User, target_id)
            await leave_project(db, actor, workspace_id, project_id)
    finally:
        resume.set()
    assert await postgres_race.join("rejoin") == "conflict"
    async with postgres_race.session("verify-rejected") as db:
        rows = (
            await db.scalars(
                select(ProjectParticipant).where(
                    ProjectParticipant.project_id == project_id,
                    ProjectParticipant.user_id == target_id,
                )
            )
        ).all()
        assert rows == []
        join_events = select(func.count(AuditEvent.id)).where(
            AuditEvent.project_id == project_id,
            AuditEvent.action == "project.participant.join",
        )
        assert await db.scalar(join_events) == 1
        assert (
            await db.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.project_id == project_id,
                    AuditEvent.action == "project.participant.leave",
                )
            )
            == 1
        )
        actor = await db.get(User, target_id)
        fresh_selection = await join_project(db, actor, workspace_id, project_id)
        assert fresh_selection.id != old_selection_id
        assert await db.scalar(join_events) == 2
