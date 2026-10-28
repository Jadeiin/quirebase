---
title: Manage Workspaces and members
description: Invite existing Users, choose roles, transfer ownership, and manage Workspace lifecycle.
---

Workspace governance belongs to the Workspace owner and the actions delegated to its admins.
An instance administrator does not gain implicit access to its research data. The application shows
the available actions and target role choices after evaluating current authority and lifecycle.

## Choose roles for the work

These summaries describe common responsibilities in an active, unfrozen Workspace. Individual
operations also check resource relations, participation, authorship, and current state.

| Role | Typical responsibilities |
| --- | --- |
| `owner` | Workspace governance, ownership transfer, and permanent deletion of an archived Workspace |
| `admin` | Delegated membership governance, content moderation, and permanent Item deletion |
| `editor` | Import and maintain Items and files, assign Tags, and organize working Projects |
| `reviewer` | Contribute Project Annotations, Replies, and Discussions |
| `viewer` | Read and export content, with personal private Annotations |

All five roles can create their own private Annotations in an active Workspace. A viewer cannot
therefore be treated as having no writes of any kind. Project participation adds no extra authority
over canonical Workspace Items.

The [generated authorization matrix](https://github.com/Jadeiin/quirebase/blob/main/docs/architecture/authorization-matrix.md)
contains the exact resource-action grants. It is maintained from policy rather than duplicated as
a second complete table here.

## Invite an existing User

1. Open **Workspace settings → Invitations**.
2. Enter the User's exact username, choose an available role and expiration period, and create the
   Invitation.
3. Copy the one-time link and send it to the intended person through your normal communication
   channel. The secret is not shown again in invitation history.
4. The recipient signs in as that User and accepts the invitation. Received invitations are also
   listed under **My workspaces**.
5. Verify the new membership in **Workspace settings → Members**.

This admits an existing User; creating an account uses a separate instance Invitation. If the link
is expired or revoked, create a new invitation. Rejoining after termination creates a new membership
generation and does not restore previous Project selections.

## Change membership and ownership

Use **Members** to change one of the target's available roles, suspend, reactivate, or terminate
membership. An owner can govern admins; an admin's choices for other members are narrower.
Suspension removes effective access but preserves Project selections. Termination removes those
selections while preserving content and authorship.

To hand over ownership, the owner chooses **Transfer ownership** for an eligible active member and
reviews the confirmation. The new member becomes owner and the previous owner becomes admin.
An owner must transfer ownership before leaving the Workspace.

User deactivation removes effective access but preserves the ownership assignment. When normal
transfer is unavailable, an instance administrator can explicitly reassign ownership to an active
User with a recorded reason. Reassignment is a distinct governance operation, not automatic access
for the administrator.

## Archive, freeze, or delete a Workspace

Under **Workspace settings → Advanced**, authorized governors can reindex, archive, or restore the
Workspace. Archived content stays readable and exportable while ordinary mutations are disabled.

An instance administrator can impose a read-only freeze. It preserves membership and the underlying
active or archived state, but blocks Workspace mutations and governance-list access. Unfreezing is
an instance operation; ordinary Workspace restoration does not remove the freeze.

Permanent Workspace deletion is owner-only and requires an archived, unfrozen Workspace. It removes
the Workspace and its content, with durable cleanup of stored objects. Export or back up what you
need before using **Permanently delete workspace**. Deleting a Project or removing one Item from a
Project has a different scope; see [collaboration](/guides/collaboration/).
