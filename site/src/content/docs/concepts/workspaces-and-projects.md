---
title: Workspaces, Projects, and access
description: Understand the governance boundary and the collaborative contexts inside it.
---

A **Workspace** governs its Items, files, Tags, Discussions, and Projects. Every owned research
resource has one Workspace lineage. There is no separate personal or shared Workspace kind;
the Workspace created for a new User follows the same rules as every other Workspace.

A **Project** organizes a working set of Items inside one Workspace and holds Project-scoped
Annotations and Discussions. It has no owner. Creating a Project records provenance, not an
additional ownership role.

## Two levels of authority

The instance **System Role** is `administrator` or `member`. It governs account and instance
operations. Being an instance administrator does not grant implicit research-data access.

The **Workspace Role** is `owner`, `admin`, `editor`, `reviewer`, or `viewer`. It participates in
resource-action decisions such as `item.update` or `item.delete`. Active User status and an active
membership are required for effective data access. Authorship records provenance separately.

Project participation grants no additional Workspace authority or canonical Item access. The
application shows actions based on server decisions and resource lifecycle; a role name alone does
not mean every operation is available.

For exact grants, contributors can consult the generated
[authorization matrix](https://github.com/Jadeiin/quirebase/blob/main/docs/architecture/authorization-matrix.md).

## Read-only and membership states

- A **Workspace Freeze** is an administrator read-only overlay. It blocks mutations while retaining
  active members' content reads, downloads, and exports. It does not grant administrator access.
- Archiving preserves a Workspace or Project for restoration and affects available operations.
- Suspending membership removes effective access while retaining participation selections.
- Terminating membership removes access and its Project selections. A new Invitation creates a new
  membership generation.

Workspace ownership remains assigned when its User is deactivated. An instance administrator can
explicitly reassign ownership to an active User with a recorded reason; that is distinct from
implicit administrator content access.

See [collaboration](/guides/collaboration/) for invitations and participation modes.
