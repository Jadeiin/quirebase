---
title: Understand Workspace and Project access
description: Decide where research belongs, who can read it, and what Project participation changes.
---

A **Workspace** is the governance and access boundary for its Items, files, Tags, Discussions, and
Projects. A **Project** is a working set and collaboration context inside one Workspace.

## Use a Workspace for a membership boundary

For example, Alice has a Workspace created with her account. Bob does not gain access to it simply
by having an account on the same instance. Alice or an authorized governor must admit Bob to that
Workspace and choose his role.

There is no separate personal/shared Workspace type. A Workspace used only by Alice follows the
same rules as a team Workspace. An Item, its files, and its ordinary associations keep one Workspace
lineage. Copying an Item into another Workspace creates an independent record.

## Use a Project for a collaborative context

Within their Workspace, Alice and Bob can add an Item to a reading Project. The Project can hold its
own Annotations and Discussions, while the Item remains in the Workspace Library. Adding it to a
second Project does not duplicate the bibliographic record.

Project participation has no separate owner/editor/viewer role and grants no extra authority over
the canonical Item. A managed Project limits who discovers its context; it does not make the
underlying Item private from other authorized Workspace readers. A Project has no owner; its
creator is recorded as provenance.

## Separate instance and Workspace roles

| Level | Role values | Controls |
| --- | --- | --- |
| System Role | `administrator`, `member` | Account operations and instance governance |
| Workspace Role | `owner`, `admin`, `editor`, `reviewer`, `viewer` | Specific research-content and membership actions |

An instance administrator has no implicit research-content access. Workspace access needs an active
User and active membership, then the relevant resource-action and lifecycle checks. Private
Annotations remain restricted to their author. Ownership reassignment and reason-bound read-only
inspection are explicit instance operations, not a general grant to browse content.

For practical role choices, follow [member management](/administration/workspaces-and-members/).
The repository's generated [authorization matrix](https://github.com/Jadeiin/quirebase/blob/main/docs/architecture/authorization-matrix.md)
contains exact grants.

## Understand why an action becomes unavailable

| State or change | Reads | Ordinary changes | Recovery |
| --- | --- | --- | --- |
| Active Workspace and membership | According to authority | According to authority | Use the relevant task guide |
| Archived Workspace | Content remains readable/exportable | Disabled | An authorized governor restores the Workspace |
| Administrative freeze | Active members retain content reads/downloads/exports | Blocked, including restoration and governance-list access | An instance administrator unfreezes it |
| Suspended membership | Effective content access removed | Disabled for that member | An authorized governor reactivates membership |
| Terminated membership or leaving | Effective content access removed | Disabled | A new invitation creates a new membership generation |

Suspension retains explicit Project selections; termination removes them. Rejoining does not restore
previous selections. Deactivating a User removes effective authority while preserving the Workspace
ownership assignment and content provenance. Ownership transfer or administrative reassignment is
an explicit operation.

For a complete shared-reading procedure, continue with [Project collaboration](/guides/collaboration/).
