---
title: Manage Workspaces and members
description: Choose roles, invite an existing User, transfer ownership, and handle archived or frozen Workspaces.
---

Workspace owners and delegated admins manage research membership. Instance administration and
Workspace governance are separate: being an instance administrator does not automatically admit you
to another Workspace's research content.

## Choose a role for the person's task

These responsibilities assume an active User, active membership, and an active, unfrozen Workspace.
Concrete operations also check participation, authorship, resource relations, and lifecycle.

| Role | Typical responsibility | Important boundary |
| --- | --- | --- |
| `owner` | Workspace governance and ownership transfer | Only the owner can permanently delete an archived Workspace |
| `admin` | Delegated membership governance, moderation, and Item deletion | Governing admins and ownership is more restricted |
| `editor` | Import, metadata/files, Tags assignments, working Projects | Permanent Item deletion is not an editor grant |
| `reviewer` | Shared Annotations, Replies, and Discussions | Does not maintain canonical bibliographic metadata/files |
| `viewer` | Read/export content and keep personal private notes | Does not create shared Project Annotations |

All five roles can create their own private Annotations in an active Workspace. Project participation
does not add extra Item permissions. For exact grants, consult the generated
[authorization matrix](https://github.com/Jadeiin/quirebase/blob/main/docs/architecture/authorization-matrix.md).

## Invite an existing User

1. Confirm the recipient already has an instance account. If needed, ask the instance administrator
   to provision it with an account Invitation first.
2. Open **Workspace settings → Invitations**.
3. Enter the exact username, choose one of the offered roles and an expiry, then **Create invitation**.
4. Copy the one-time link and deliver it to the intended recipient. It is not recoverable from history.
5. The recipient signs in as that User and accepts, either through the link or **My workspaces**.
6. Verify their active membership in **Workspace settings → Members**.

A link for one User cannot be accepted by another signed-in User. For an expired or revoked link,
create a new invitation. Suspending a membership is handled through membership reactivation, while
termination and later admission create a new membership generation.

## Change a member's role or state

In **Members**, locate the target and use the offered role choices or lifecycle action. The UI offers
only transitions your current authority allows. Owners can govern admins; admins have narrower
choices for ordinary members.

- **Suspend** removes effective access while preserving content, authorship, and Project selections.
- **Reactivate** restores the suspended membership's effective participation when other conditions allow.
- **Terminate** ends that generation and removes its explicit Project selections. Content and
  authorship remain. Rejoining requires a new invitation and does not restore those selections.

An active non-owner can leave an active, unfrozen Workspace. Leaving has termination semantics for
that membership; it does not delete the person's research contributions.

## Transfer or reassign ownership

The current owner chooses **Transfer ownership** for an eligible active member and reviews the
confirmation. The recipient becomes owner; the former owner becomes admin. Transfer ownership
before the owner leaves or their membership is removed.

User deactivation preserves the structural ownership assignment but removes effective authority.
If ordinary transfer cannot be performed, an instance administrator can explicitly reassign
ownership to an active User with a recorded reason. This can grant the receiving User owner access;
it does not implicitly grant content access to the administrator executing it.

## Archive, freeze, restore, and delete

| Operation | Where to perform it | Effect |
| --- | --- | --- |
| Archive / restore | **Workspace settings → Advanced**, when authorized | Preserve a readable/exportable Workspace and later restore it |
| Reindex | **Advanced**, when authorized | Rebuild this Workspace's Library Search projection |
| Freeze / unfreeze | Instance governance | Impose/remove an administrative read-only overlay without changing membership or underlying archive state |
| Permanently delete | **Advanced**, owner only | Remove an archived, unfrozen Workspace and its content |

A frozen Workspace also blocks restoration and governance-list access until an instance administrator
unfreezes it. Restoring an archived Workspace does not bypass a freeze. Permanent deletion has no
Undo; preserve required content and backups first. Deleting a Project or removing one Project–Item
association has a different scope, described in [collaboration](/guides/collaboration/).
