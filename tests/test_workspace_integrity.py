"""Database invariants, diagnostic findings, and retained historical context."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from typer.testing import CliRunner
from workspace_helpers import fixture_membership_id

from quirebase.audit import record_event
from quirebase.models import (
    AuditEvent,
    Project,
    ProjectParticipant,
    ProjectParticipation,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
)
from quirebase.projects import add_project_participant, check_project_integrity, create_project
from quirebase.workspaces import (
    archive_workspace,
    check_workspace_integrity,
    permanently_delete_workspace,
    provision_initial_workspace,
    suspend_workspace_member,
    terminate_workspace_member,
    workspace_owner_ids,
)


@pytest.fixture(
    params=[
        pytest.param("async_session_factory", id="sqlite"),
        pytest.param("postgres_sessions", id="postgres", marks=pytest.mark.shared_postgres),
    ]
)
def integrity_sessions(request):
    factory = request.getfixturevalue(request.param)
    if request.param == "postgres_sessions":
        request.getfixturevalue("postgres_search_tables")
    return factory


async def _workspace(db):
    owner = User(username="integrity-owner", password_hash="unused", role="administrator")
    participant = User(username="integrity-participant", password_hash="unused")
    db.add_all([owner, participant])
    await db.flush()
    workspace = await provision_initial_workspace(db, owner)
    member = WorkspaceMember(
        workspace_id=workspace.id, user_id=participant.id, role=WorkspaceRole.viewer
    )
    db.add(member)
    await db.commit()
    return owner, participant, workspace, member


@pytest.mark.anyio
@pytest.mark.parametrize("invalid_state", ["suspended", "terminated"])
async def test_database_rejects_inactive_owner_memberships(integrity_sessions, invalid_state):
    async with integrity_sessions() as db:
        owner, _, workspace, _ = await _workspace(db)
        values = (
            {"state": WorkspaceMemberState.suspended}
            if invalid_state == "suspended"
            else {"terminated_at": datetime.now(UTC)}
        )
        with pytest.raises(IntegrityError):
            async with db.begin_nested():
                await db.execute(
                    update(WorkspaceMember)
                    .where(
                        WorkspaceMember.workspace_id == workspace.id,
                        WorkspaceMember.user_id == owner.id,
                    )
                    .values(**values)
                )
        assert await check_workspace_integrity(db) == []


@pytest.mark.anyio
@pytest.mark.parametrize("corruption", ["missing_owner", "removed_membership", "inactive_account"])
async def test_owner_lookup_and_diagnostics_reject_invalid_surviving_roots(
    integrity_sessions, corruption
):
    async with integrity_sessions() as db:
        owner, _, workspace, _ = await _workspace(db)
        workspace_id = workspace.id
        assert await workspace_owner_ids(db, {workspace_id, uuid4()}) == {workspace_id: owner.id}
        if corruption == "missing_owner":
            await db.execute(
                update(WorkspaceMember)
                .where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == owner.id,
                )
                .values(role=WorkspaceRole.admin)
            )
        elif corruption == "removed_membership":
            membership = await db.scalar(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == owner.id,
                )
            )
            await db.delete(membership)
        else:
            owner.active = False
        await db.commit()
        with pytest.raises(RuntimeError, match=str(workspace_id)):
            await workspace_owner_ids(db, {workspace_id})
        findings = await check_workspace_integrity(db)
        assert len(findings) == 1 and str(workspace_id) in findings[0]


@pytest.mark.anyio
async def test_project_diagnostics_respect_retained_participation_and_detect_drift(
    integrity_sessions,
):
    async with integrity_sessions() as db:
        owner, participant, workspace, member = await _workspace(db)
        implicit = await create_project(
            db, owner, workspace.id, "Implicit", participation=ProjectParticipation.workspace
        )
        managed = await create_project(
            db, owner, workspace.id, "Managed", ProjectParticipation.managed
        )
        await add_project_participant(db, owner, workspace.id, managed.id, participant.username)
        assert await check_project_integrity(db) == []
        await suspend_workspace_member(db, owner, workspace.id, member.id)
        participant.active = False
        await db.commit()
        assert await check_project_integrity(db) == []

        # Simulate a maintenance write that bypasses the termination command.
        member.terminated_at = datetime.now(UTC)
        await db.commit()
        findings = await check_project_integrity(db)
        explicit = await db.scalar(
            select(ProjectParticipant).where(ProjectParticipant.project_id == managed.id)
        )
        assert len(findings) == 1 and str(explicit.id) in findings[0]
        member.terminated_at = None
        await db.commit()
        await terminate_workspace_member(db, owner, workspace.id, member.id)
        assert await check_project_integrity(db) == []

        # A current member on a Workspace-mode Project violates implicit participation.
        db.add(
            WorkspaceMember(
                workspace_id=workspace.id, user_id=participant.id, role=WorkspaceRole.viewer
            )
        )
        db.add(
            ProjectParticipant(
                workspace_id=workspace.id,
                project_id=implicit.id,
                user_id=participant.id,
                workspace_member_id=await fixture_membership_id(db, workspace.id, participant.id),
            )
        )
        await db.commit()
        findings = await check_project_integrity(db)
        assert len(findings) == 1 and str(implicit.id) in findings[0]


@pytest.mark.anyio
async def test_permanent_workspace_delete_retains_audit_project_history(integrity_sessions):
    async with integrity_sessions() as db:
        owner, _, workspace, _ = await _workspace(db)
        project = await create_project(db, owner, workspace.id, "Historical Project")
        event = record_event(
            db,
            owner.id,
            "project.history",
            "project",
            project.id,
            workspace_id=workspace.id,
            project_id=project.id,
        )
        await db.commit()
        workspace_id, project_id, event_id = workspace.id, project.id, event.id
        await archive_workspace(db, owner, workspace_id)
        workspace.archived_at = datetime.now(UTC) - timedelta(days=3650)
        await db.commit()
        await permanently_delete_workspace(db, owner, workspace_id)
    async with integrity_sessions() as fresh:
        assert await fresh.get(Workspace, workspace_id) is None
        assert await fresh.get(Project, project_id) is None
        retained = await fresh.get(AuditEvent, event_id)
        assert retained.workspace_id == workspace_id
        assert retained.project_id == project_id
        assert await workspace_owner_ids(fresh, {workspace_id}) == {}
        assert await check_workspace_integrity(fresh) == []
        assert await check_project_integrity(fresh) == []


@pytest.mark.anyio
async def test_doctor_reports_domain_integrity_failures(async_session_factory, monkeypatch):
    from quirebase import cli

    async with async_session_factory() as db:
        owner, _, _, _ = await _workspace(db)
        owner.active = False
        await db.commit()

    async def verified_workflows():
        pass

    monkeypatch.setattr(cli, "engine", async_session_factory.kw["bind"])
    monkeypatch.setattr(cli, "AsyncSessionLocal", async_session_factory)
    monkeypatch.setattr(cli, "verify_durable_operations", verified_workflows)
    result = await anyio.to_thread.run_sync(lambda: CliRunner().invoke(cli.app, ["doctor"]))
    assert result.exit_code == 1, result.output
    assert "[ok] object integrity" in result.output
    assert "[failed] domain Workspace" in result.output
    assert "active account" in result.output


@pytest.mark.anyio
@pytest.mark.parametrize("mismatch", ["workspace", "user", "missing_member"])
async def test_participant_database_lineage_rejects_mismatched_membership(
    integrity_sessions, mismatch
):
    async with integrity_sessions() as db:
        owner, participant, workspace, member = await _workspace(db)
        project = await create_project(
            db, owner, workspace.id, "Lineage", ProjectParticipation.managed
        )
        foreign = await provision_initial_workspace(db, participant)
        foreign_member_id = await fixture_membership_id(db, foreign.id, participant.id)
        values = {
            "workspace_id": workspace.id,
            "project_id": project.id,
            "workspace_member_id": member.id,
            "user_id": participant.id,
        }
        if mismatch == "workspace":
            values["workspace_member_id"] = foreign_member_id
        elif mismatch == "user":
            values["user_id"] = owner.id
        else:
            values["workspace_member_id"] = uuid4()
        async with db.begin_nested() as savepoint:
            with pytest.raises(IntegrityError):
                await db.execute(insert(ProjectParticipant).values(**values))
            await savepoint.rollback()
        assert (
            await db.scalar(
                select(ProjectParticipant.id).where(ProjectParticipant.project_id == project.id)
            )
            is None
        )
        assert await check_project_integrity(db) == []


@pytest.mark.anyio
async def test_participation_belongs_to_one_membership_generation(integrity_sessions):
    from quirebase.workspaces import reactivate_workspace_member

    async with integrity_sessions() as db:
        owner, participant, workspace, member = await _workspace(db)
        project = await create_project(
            db, owner, workspace.id, "Generations", ProjectParticipation.managed
        )
        await add_project_participant(db, owner, workspace.id, project.id, participant.username)
        selection = await db.scalar(
            select(ProjectParticipant).where(ProjectParticipant.project_id == project.id)
        )
        selection_id, old_member_id = selection.id, member.id
        assert selection.workspace_member_id == old_member_id
        await suspend_workspace_member(db, owner, workspace.id, member.id)
        await reactivate_workspace_member(db, owner, workspace.id, member.id)
        assert (await db.get(ProjectParticipant, selection_id)).workspace_member_id == old_member_id
        await terminate_workspace_member(db, owner, workspace.id, member.id)
        new_member = WorkspaceMember(
            workspace_id=workspace.id, user_id=participant.id, role=WorkspaceRole.viewer
        )
        db.add(new_member)
        await db.commit()
        assert new_member.id != old_member_id
        assert (
            await db.scalar(
                select(ProjectParticipant.id).where(ProjectParticipant.project_id == project.id)
            )
            is None
        )
        await add_project_participant(db, owner, workspace.id, project.id, participant.username)
        current = await db.scalar(
            select(ProjectParticipant).where(ProjectParticipant.project_id == project.id)
        )
        assert current.workspace_member_id == new_member.id
        # Physical membership deletion also cascades the selection at the database boundary.
        await db.delete(new_member)
        await db.commit()
        assert (
            await db.scalar(
                select(ProjectParticipant.id).where(ProjectParticipant.project_id == project.id)
            )
            is None
        )


@pytest.mark.anyio
@pytest.mark.parametrize("mode", [ProjectParticipation.open, ProjectParticipation.managed])
async def test_stale_selection_cannot_attach_to_a_later_membership(integrity_sessions, mode):
    from quirebase.access import discoverable_project_ids_query, resolve_workspace_context
    from quirebase.projects import join_project, list_workspace_projects, open_project_workspace

    async with integrity_sessions() as db:
        owner, participant, workspace, member = await _workspace(db)
        project = await create_project(db, owner, workspace.id, "Historical selection", mode)
        if mode is ProjectParticipation.open:
            await join_project(db, participant, workspace.id, project.id)
        else:
            await add_project_participant(db, owner, workspace.id, project.id, participant.username)
        # Simulate a maintenance write that neglected the command's relation cleanup.
        member.terminated_at = datetime.now(UTC)
        await db.commit()
        db.add(
            WorkspaceMember(
                workspace_id=workspace.id, user_id=participant.id, role=WorkspaceRole.viewer
            )
        )
        await db.commit()
        context = await resolve_workspace_context(db, participant, workspace.id)
        mine, total = await list_workspace_projects(db, context, view="mine")
        assert mine == [] and total == 0
        if mode is ProjectParticipation.managed:
            assert project.id not in set(
                (await db.scalars(discoverable_project_ids_query(context))).all()
            )
        else:
            assert not (await open_project_workspace(db, context, project.id)).is_participating
        owner_context = await resolve_workspace_context(db, owner, workspace.id)
        opened = await open_project_workspace(db, owner_context, project.id)
        assert participant.id not in {p.user_id for p in opened.active_participants}
        assert len(await check_project_integrity(db)) == 1
