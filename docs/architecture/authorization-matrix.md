# Effective Workspace capabilities

Generated from the immutable Casbin bundle and action schema. Regenerate with
`uv run python scripts/export-authorization-matrix.py`; CI checks this artifact.

A = active Workspace, R = archived Workspace, F = administrative read-only freeze.
A dash means denied in all three lifecycles. Each row uses a valid action relation;
relations are internal request facts, rather than a public API policy language.

This is capability policy for an already resolved active User/Workspace membership.
Project participation, visibility, target state, lineage and owner invariants remain
domain rules; this table alone does not establish permission for a concrete command.

| Resource action | Relation | owner | admin | editor | reviewer | viewer |
| --- | --- | --- | --- | --- | --- | --- |
| `citation_style.manage` | `any` | A | A | A | — | — |
| `file.delete` | `any` | A | A | A | — | — |
| `file.manage` | `any` | A | A | A | — | — |
| `item.copy` | `any` | A | A | A | — | — |
| `item.create` | `any` | A | A | A | — | — |
| `item.delete` | `any` | A | A | — | — | — |
| `item.update` | `any` | A | A | A | — | — |
| `item_discussion.create` | `any` | A | A | A | A | — |
| `item_discussion.delete` | `other` | A | A | — | — | — |
| `item_discussion.delete` | `own` | A | A | A | A | — |
| `private_annotation.create` | `own` | A | A | A | A | A |
| `private_annotation.delete` | `own` | A | A | A | A | A |
| `private_annotation.read` | `own` | A/R/F | A/R/F | A/R/F | A/R/F | A/R/F |
| `private_annotation.restore` | `own` | A | A | A | A | A |
| `private_annotation.update` | `own` | A | A | A | A | A |
| `private_annotation_reply.create` | `own` | A | A | A | A | A |
| `private_annotation_reply.delete` | `own` | A | A | A | A | A |
| `private_annotation_reply.restore` | `own` | A | A | A | A | A |
| `private_annotation_reply.update` | `own` | A | A | A | A | A |
| `project.archive` | `any` | A | A | A | — | — |
| `project.create` | `managed` | A | A | — | — | — |
| `project.create` | `open` | A | A | A | — | — |
| `project.create` | `workspace` | A | A | A | — | — |
| `project.delete` | `any` | A | A | — | — | — |
| `project.restore` | `any` | A | A | A | — | — |
| `project.update` | `any` | A | A | A | — | — |
| `project_annotation.archive` | `other` | A | A | — | — | — |
| `project_annotation.create` | `own` | A | A | A | A | — |
| `project_annotation.delete` | `other` | A | A | — | — | — |
| `project_annotation.delete` | `own` | A | A | A | A | — |
| `project_annotation.hide` | `other` | A | A | — | — | — |
| `project_annotation.lock` | `other` | A | A | — | — | — |
| `project_annotation.read` | `other` | A/R/F | A/R/F | A/R/F | A/R/F | A/R/F |
| `project_annotation.read` | `own` | A/R/F | A/R/F | A/R/F | A/R/F | A/R/F |
| `project_annotation.restore` | `other` | A | A | — | — | — |
| `project_annotation.restore` | `own` | A | A | A | A | — |
| `project_annotation.review` | `any` | A/R/F | A/R/F | — | — | — |
| `project_annotation.unlock` | `other` | A | A | — | — | — |
| `project_annotation.update` | `own` | A | A | A | A | — |
| `project_annotation_reply.create` | `other` | A | A | A | A | — |
| `project_annotation_reply.create` | `own` | A | A | A | A | — |
| `project_annotation_reply.delete` | `own` | A | A | A | A | — |
| `project_annotation_reply.restore` | `own` | A | A | A | A | — |
| `project_annotation_reply.update` | `own` | A | A | A | A | — |
| `project_discussion.create` | `any` | A | A | A | A | — |
| `project_discussion.delete` | `other` | A | A | — | — | — |
| `project_discussion.delete` | `own` | A | A | A | A | — |
| `project_governance.read` | `any` | A/R/F | A/R/F | — | — | — |
| `project_item.manage` | `any` | A | A | A | — | — |
| `project_membership.join` | `open` | A | A | A | A | A |
| `project_membership.leave` | `open` | A | A | A | A | A |
| `project_membership.manage` | `managed` | A | A | — | — | — |
| `tag.create` | `any` | A | A | A | — | — |
| `tag.manage` | `any` | A | A | — | — | — |
| `tag.use` | `any` | A | A | A | — | — |
| `workspace.archive` | `any` | A | A | — | — | — |
| `workspace.delete` | `any` | R | — | — | — | — |
| `workspace.export` | `any` | A/R/F | A/R/F | A/R/F | A/R/F | A/R/F |
| `workspace.read` | `any` | A/R/F | A/R/F | A/R/F | A/R/F | A/R/F |
| `workspace.restore` | `any` | R | R | — | — | — |
| `workspace.update` | `any` | A | A | — | — | — |
| `workspace_invitation.create` | `admin` | A | — | — | — | — |
| `workspace_invitation.create` | `member` | A | A | — | — | — |
| `workspace_invitation.read` | `any` | A/R | A/R | — | — | — |
| `workspace_invitation.revoke` | `any` | A | A | — | — | — |
| `workspace_maintenance.run` | `any` | A | A | — | — | — |
| `workspace_member.change_role` | `admin` | A | — | — | — | — |
| `workspace_member.change_role` | `member` | A | A | — | — | — |
| `workspace_member.promote` | `member` | A | — | — | — | — |
| `workspace_member.reactivate` | `admin` | A | — | — | — | — |
| `workspace_member.reactivate` | `member` | A | A | — | — | — |
| `workspace_member.read` | `any` | A/R | A/R | — | — | — |
| `workspace_member.suspend` | `admin` | A | — | — | — | — |
| `workspace_member.suspend` | `member` | A | A | — | — | — |
| `workspace_member.terminate` | `admin` | A | — | — | — | — |
| `workspace_member.terminate` | `member` | A | A | — | — | — |
| `workspace_member.transfer_ownership` | `admin` | A | — | — | — | — |
| `workspace_member.transfer_ownership` | `member` | A | — | — | — | — |
