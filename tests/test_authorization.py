from __future__ import annotations

import csv
from pathlib import Path

from quirebase.access import (
    ResourceAction,
    SystemAction,
    effective_system_actions,
    initialize_authorization,
    system_action_allowed,
    workspace_member_relation,
)
from quirebase.access.authorization import _enforce_canonical, workspace_action_allowed
from quirebase.access.workspace_policy import ACTION_SPECS, action_spec
from quirebase.models import SystemRole, WorkspaceRole, WorkspaceState


def _policy_rows() -> list[list[str]]:
    policy_path = (
        Path(__file__).parent.parent / "src" / "quirebase" / "access" / "policy" / "policy.csv"
    )
    return [
        [part.strip() for part in row]
        for row in csv.reader(policy_path.read_text(encoding="utf-8").splitlines())
        if row and row[0].strip() == "p"
    ]


def test_immutable_casbin_bundle_initializes():
    initialize_authorization()


def test_workspace_action_metadata_is_complete_and_classifies_reads():
    assert set(ACTION_SPECS) == set(ResourceAction)
    for action in (
        ResourceAction.workspace_read,
        ResourceAction.workspace_export,
        ResourceAction.workspace_member_read,
        ResourceAction.workspace_invitation_read,
        ResourceAction.project_discover,
    ):
        assert not action_spec(action).mutating
    assert action_spec(ResourceAction.project_create).relations == (
        "workspace",
        "open",
        "managed",
    )
    assert action_spec(ResourceAction.project_update).relation_projection == "resource"


def test_every_declared_workspace_and_system_action_has_policy_coverage():
    rows = _policy_rows()
    workspace_actions = {(row[2], row[3]) for row in rows if row[1].startswith("workspace:")}
    system_actions = {(row[2], row[3]) for row in rows if row[1].startswith("system:")}

    assert workspace_actions == {
        (resource_action.resource, resource_action.action) for resource_action in ResourceAction
    }
    assert system_actions == {(action.resource, action.action) for action in SystemAction}
    assert all("." not in row[3] for row in rows)


def test_system_policy_has_no_preliminary_administration_gate():
    assert all(row[2:4] != ["administration", "access"] for row in _policy_rows())


def test_policy_rows_are_unique_and_stably_grouped_by_role_resource_and_action():
    rows = _policy_rows()
    subject_order = {
        "workspace:viewer": 0,
        "workspace:reviewer": 1,
        "workspace:editor": 2,
        "workspace:admin": 3,
        "workspace:owner": 4,
        "system:member": 5,
        "system:administrator": 6,
    }
    keys = [(subject_order[row[1]], row[2], row[3], row[4], row[5]) for row in rows]

    assert len(rows) == len({tuple(row) for row in rows})
    assert keys == sorted(keys)


def test_policy_uses_canonical_crud_verbs_without_authorization_synonyms():
    actions = {row[3] for row in _policy_rows()}

    assert actions.isdisjoint({
        "edit",
        "list",
        "moderate",
        "moderate_delete",
        "read_metrics",
        "revoke_all",
        "restore_moderated",
        "write",
        "create_admins_only",
        "create_managed",
        "create_members_allowed",
    })


def test_system_roles_are_decided_only_by_the_casbin_action_matrix():
    unconstrained_policy_actions = {
        (row[2], row[3])
        for row in _policy_rows()
        if row[1] in {"system:member", "system:administrator"} and row[5] == "any"
    }
    assert effective_system_actions(SystemRole.member) == frozenset()
    expected_unconstrained = {
        action
        for action in SystemAction
        if (action.resource, action.action) in unconstrained_policy_actions
    }
    assert effective_system_actions(SystemRole.administrator) == frozenset(expected_unconstrained)
    assert all(not system_action_allowed(SystemRole.member, action) for action in SystemAction)
    assert system_action_allowed(
        SystemRole.member,
        SystemAction.workspaces_create,
        relation="members_allowed",
    )
    assert not system_action_allowed(
        SystemRole.member,
        SystemAction.workspaces_create,
        relation="admins_only",
    )
    assert system_action_allowed(
        SystemRole.administrator,
        SystemAction.workspaces_create,
        relation="admins_only",
    )
    assert system_action_allowed(
        SystemRole.member,
        SystemAction.account_change_password,
        relation="own",
    )
    assert not system_action_allowed(SystemRole.member, SystemAction.account_change_password)


def test_policy_decisions_and_system_projection_reuse_immutable_results():
    actions = effective_system_actions(SystemRole.administrator)
    assert effective_system_actions(SystemRole.administrator) is actions

    _enforce_canonical.cache_clear()
    assert workspace_action_allowed(WorkspaceRole.editor, "item", "copy", WorkspaceState.active)
    first = _enforce_canonical.cache_info()
    assert workspace_action_allowed(WorkspaceRole.editor, "item", "copy", "active")
    repeated = _enforce_canonical.cache_info()
    assert repeated.misses == first.misses
    assert repeated.hits == first.hits + 1


def test_relation_policies_cover_project_membership_authorship_and_governance():
    lifecycle = WorkspaceState.active

    assert workspace_action_allowed(WorkspaceRole.editor, "item", "copy", lifecycle)
    assert not workspace_action_allowed(WorkspaceRole.reviewer, "item", "copy", lifecycle)
    assert workspace_action_allowed(
        WorkspaceRole.viewer, "project", "discover", lifecycle, "participant"
    )
    assert not workspace_action_allowed(
        WorkspaceRole.viewer, "project", "discover", lifecycle, "managed"
    )
    assert workspace_action_allowed(
        WorkspaceRole.admin, "project", "discover", lifecycle, "managed"
    )
    assert workspace_action_allowed(
        WorkspaceRole.reviewer, "project_discussion", "delete", lifecycle, "own"
    )
    assert not workspace_action_allowed(
        WorkspaceRole.reviewer, "project_discussion", "delete", lifecycle, "other"
    )
    assert workspace_action_allowed(
        WorkspaceRole.owner, "project_annotation", "delete", lifecycle, "other"
    )
    assert not workspace_action_allowed(
        WorkspaceRole.owner, "project_annotation", "hide", lifecycle, "own"
    )
    assert workspace_action_allowed(
        WorkspaceRole.admin, "workspace_member", "terminate", lifecycle, "member"
    )
    assert not workspace_action_allowed(
        WorkspaceRole.admin, "workspace_member", "terminate", lifecycle, "admin"
    )
    assert workspace_action_allowed(
        WorkspaceRole.owner, "workspace_member", "terminate", lifecycle, "admin"
    )
    assert workspace_action_allowed(
        WorkspaceRole.owner, "workspace_member", "transfer_ownership", lifecycle, "member"
    )
    assert not workspace_action_allowed(
        WorkspaceRole.owner, "workspace_member", "transfer_ownership", lifecycle, "owner"
    )


def test_workspace_member_roles_are_normalized_to_policy_relations():
    assert workspace_member_relation(WorkspaceRole.owner) == "owner"
    assert workspace_member_relation(WorkspaceRole.admin) == "admin"
    for role in (WorkspaceRole.editor, WorkspaceRole.reviewer, WorkspaceRole.viewer):
        assert workspace_member_relation(role) == "member"


def test_policy_regexes_match_complete_lifecycle_and_relation_values_only():
    lifecycle = WorkspaceState.active

    assert not workspace_action_allowed(
        WorkspaceRole.reviewer,
        "project_discussion",
        "delete",
        lifecycle,
        "owner",
    )
    assert not workspace_action_allowed(
        WorkspaceRole.admin,
        "workspace_member",
        "suspend",
        lifecycle,
        "members_allowed",
    )
    assert not workspace_action_allowed(
        WorkspaceRole.editor,
        "item",
        "update",
        "active_but_not_canonical",
    )
    assert not system_action_allowed(
        SystemRole.member,
        SystemAction.workspaces_create,
        relation="members_allowed_suffix",
    )


def test_mutating_relation_actions_fail_closed_outside_active_lifecycle():
    for lifecycle in (WorkspaceState.archived, "suspended"):
        assert not workspace_action_allowed(
            WorkspaceRole.owner,
            "project_annotation",
            "delete",
            lifecycle,
            "other",
        )
        assert not workspace_action_allowed(
            WorkspaceRole.owner,
            "workspace_member",
            "terminate",
            lifecycle,
            "admin",
        )
