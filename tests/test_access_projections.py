import pytest

from quirebase.access import ResourceAction, workspace_decisions, workspace_invitation_roles
from quirebase.models import WorkspaceRole, WorkspaceState


@pytest.mark.parametrize("role", WorkspaceRole)
@pytest.mark.parametrize("lifecycle", ["active", "archived", "suspended"])
def test_workspace_projection_separates_base_grants_and_concrete_choices(role, lifecycle):
    state = WorkspaceState.archived if lifecycle == "archived" else WorkspaceState.active
    suspended = lifecycle == "suspended"
    decisions = workspace_decisions(role, state, governance_suspended=suspended)
    invitations = workspace_invitation_roles(role, state, governance_suspended=suspended)

    assert ResourceAction.project_create not in decisions.allowed
    assert ResourceAction.workspace_invitation_create not in decisions.allowed
    assert ResourceAction.workspace_invitation_create not in decisions.variants
    if lifecycle != "active":
        assert not invitations
        assert ResourceAction.project_create not in decisions.variants
        return

    expected_invitations = {
        WorkspaceRole.owner: {"admin", "editor", "reviewer", "viewer"},
        WorkspaceRole.admin: {"editor", "reviewer", "viewer"},
    }.get(role, set())
    assert set(invitations) == expected_invitations
    expected_projects = {
        WorkspaceRole.owner: {"workspace", "open", "managed"},
        WorkspaceRole.admin: {"workspace", "open", "managed"},
        WorkspaceRole.editor: {"workspace", "open"},
    }.get(role, set())
    assert set(decisions.variants.get(ResourceAction.project_create, ())) == expected_projects
