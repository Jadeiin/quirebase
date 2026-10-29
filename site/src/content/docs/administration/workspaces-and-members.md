---
title: Manage Workspaces and members
description: Choose roles, invite an existing User, transfer ownership, and handle archived or frozen Workspaces.
---

Workspace owners and admins use **Workspace settings** to invite members, assign roles, and manage
the Workspace's state.

## Choose a role for the person's task

Choose a role for the work your colleague will do:

| Role | Common actions |
| --- | --- |
| `owner` | Manage the Workspace and admins, transfer ownership, permanently delete an archived Workspace |
| `admin` | Manage ordinary members, moderate content, delete Items |
| `editor` | Import references, maintain metadata and files, assign Tags, organize Projects |
| `reviewer` | Share Annotations, Replies, and Discussions |
| `viewer` | Read and export content, keep private notes |

All five roles can create their own private Annotations in an active Workspace. For exact grants, consult the generated
[authorization matrix](https://github.com/Jadeiin/quirebase/blob/main/docs/architecture/authorization-matrix.md).

## Invite an existing User

1. Confirm the recipient already has an instance account. If needed, ask the instance administrator
   to provision it with an account Invitation first.
2. Open **Workspace settings → Invitations**.
3. Enter the exact username, choose one of the offered roles and an expiry, then **Create invitation**.
4. Copy the one-time link and deliver it to the intended recipient.
5. The recipient signs in as that User and accepts, either through the link or **My workspaces**.
6. Verify their active membership in **Workspace settings → Members**.

Create a new invitation if the link expires or is revoked. Use **Reactivate** for a suspended
member; invite a terminated member again when they return.

## Change a member's role or state

In **Members**, locate the person and choose a new role or state. Owners manage admins; admins
manage ordinary members.

- **Suspend** removes effective access while preserving content, authorship, and Project selections.
- **Reactivate** restores the suspended membership's effective participation when other conditions allow.
- **Terminate** ends that generation and removes its explicit Project selections. Content and
  authorship remain. Arrange Project participation again when the member returns.

An active non-owner can leave an active, unfrozen Workspace. Leaving has termination semantics for
that membership; their references and Discussions remain in the Workspace.

## Transfer or reassign ownership

The current owner chooses **Transfer ownership** for an eligible active member and reviews the
confirmation. The recipient becomes owner; the former owner becomes admin. Transfer ownership
before the owner leaves or their membership is removed.

When a deactivated owner's Workspace needs a handover, an instance administrator can reassign
ownership to an active User with a recorded reason.

## Archive, freeze, restore, and delete

| Operation | Where to perform it | Effect |
| --- | --- | --- |
| Archive / restore | **Workspace settings → Advanced**, when authorized | Preserve a readable/exportable Workspace and later restore it |
| Reindex | **Advanced**, when authorized | Rebuild this Workspace's Library Search projection |
| Freeze / unfreeze | Instance governance | Make the Workspace read-only, or restore its state before the freeze |
| Permanently delete | **Advanced**, owner only | Remove an archived, unfrozen Workspace and its content |

Ask an instance administrator to unfreeze a Workspace before restoring it or managing its members.
Create a [backup](/administration/maintenance/) before permanent deletion. Deleting a Project or removing one Project–Item
association has a different scope, described in [collaboration](/guides/collaboration/).
