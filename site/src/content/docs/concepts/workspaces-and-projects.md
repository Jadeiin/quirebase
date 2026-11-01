---
title: Understand Workspace and Project access
description: Use Workspaces to manage members and research, and Projects to organize shared reading.
---

A **Workspace** is the governance and access boundary for its Items, files, Tags, Discussions, and
Projects. A **Project** is a working set and collaboration context inside one Workspace.

## Use a Workspace for a membership boundary

For example, Alice has a Workspace created with her account. She invites Bob and chooses a
Workspace role suited to their collaboration.

Personal use and team collaboration follow the same Workspace model. An Item, its files, and its
associations belong to that Workspace. Copying an Item into another Workspace creates an independent record.

## Use a Project for a collaborative context

Within their Workspace, Alice and Bob can add an Item to a reading Project. The Project can hold its
own Annotations and Discussions, while the Item remains in the Workspace Library. Two Projects
using the Item share its metadata and files.

Workspace roles determine actions on Items and files. Project participation determines who can
join that Project's shared reading and Discussions. Workspace governors select the participants
of managed Projects; the underlying references live in the Workspace Library.

## Separate instance and Workspace roles

| Level | Role values | Controls |
| --- | --- | --- |
| System Role | `administrator`, `member` | Account operations and instance governance |
| Workspace Role | `owner`, `admin`, `editor`, `reviewer`, `viewer` | Specific research-content and membership actions |

Instance administrators manage accounts, configuration, and instance maintenance. Workspace
members use research content according to their assigned roles. Private Annotations are visible
to their author; Project Annotations are shared with the Project's participants.

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

Suspension retains Project selections; termination removes them. Arrange Project participation
again when a member returns. Deactivated Users retain their contributions and ownership records.
See [member management](/administration/workspaces-and-members/) for ownership handover.

For a complete shared-reading procedure, continue with [Project collaboration](/guides/collaboration/).
