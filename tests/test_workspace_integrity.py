"""Database invariants, diagnostic findings, and retained historical context."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import anyio
import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from typer.testing import CliRunner

from quirebase.audit import record_event
from quirebase.models import (
    AuditEvent,
    Project,
    ProjectMember,
    ProjectParticipation,
    User,
    Workspace,
    WorkspaceMember,
    WorkspaceMemberState,
    WorkspaceRole,
)
from quirebase.projects import add_project_member, check_project_integrity, create_project
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
        await add_project_member(db, owner, workspace.id, managed.id, participant.username)
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
            select(ProjectMember).where(ProjectMember.project_id == managed.id)
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
            ProjectMember(workspace_id=workspace.id, project_id=implicit.id, user_id=participant.id)
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
