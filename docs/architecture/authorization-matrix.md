# Effective Workspace capabilities

Generated from the immutable Casbin bundle and action schema. Regenerate with
`uv run python scripts/export-authorization-matrix.py`; CI checks this artifact.

A = active Workspace, R = archived Workspace, F = administrative read-only freeze.
A dash means denied in all three lifecycles. Each row uses a valid action relation;
relations are internal request facts, rather than a public API policy language.

This is capability policy for an already resolved active User/Workspace membership.
Project participation, discoverability, target state, lineage and owner invariants remain
domain rules; this table alone does not establish permission for a concrete command.

| Resource action | Relation | owner | admin | editor | reviewer | viewer |
| --- | --- | --- | --- | --- | --- | --- |
| `citation_style.manage` | `any` | A | A | A | — | — |
| `file.delete` | `any` | A | A | A | — | — |
| `file.manage` | `any` | A | A | A | — | — |
| `item.create` | `any` | A | A | A | — | — |
| `item.delete` | `any` | A | A | — | — | — |
| `item.update` | `any` | A | A | A | — | — |
| `item_discussion.create` | `any` | A | A | A | A | — |
| `item_discussion.delete` | `other` | A | A | — | — | — |
| `item_discussion.delete` | `own` | A | A | A | A | — |
| `private_annotation.create` | `other` | — | — | — | — | — |
| `private_annotation.create` | `own` | A | A | A | A | A |
| `private_annotation.delete` | `other` | — | — | — | — | — |
| `private_annotation.delete` | `own` | A | A | A | A | A |
| `private_annotation.read` | `other` | — | — | — | — | — |
| `private_annotation.read` | `own` | A/R/F | A/R/F | A/R/F | A/R/F | A/R/F |
| `private_annotation.restore` | `other` | — | — | — | — | — |
| `private_annotation.restore` | `own` | A | A | A | A | A |
| `private_annotation.update` | `other` | — | — | — | — | — |
| `private_annotation.update` | `own` | A | A | A | A | A |
| `private_annotation_reply.create` | `other` | — | — | — | — | — |
| `private_annotation_reply.create` | `own` | A | A | A | A | A |
| `private_annotation_reply.delete` | `other` | — | — | — | — | — |
| `private_annotation_reply.delete` | `own` | A | A | A | A | A |
| `private_annotation_reply.restore` | `other` | — | — | — | — | — |
| `private_annotation_reply.restore` | `own` | A | A | A | A | A |
| `private_annotation_reply.update` | `other` | — | — | — | — | — |
| `private_annotation_reply.update` | `own` | A | A | A | A | A |
| `project.archive` | `any` | A | A | A | — | — |
| `project.create` | `managed` | A | A | — | — | — |
| `project.create` | `open` | A | A | A | — | — |
| `project.create` | `workspace` | A | A | A | — | — |
| `project.delete` | `any` | A | A | — | — | — |
| `project.restore` | `any` | A | A | A | — | — |
| `project.update` | `any` | A | A | A | — | — |
| `project_annotation.archive` | `other` | A | A | — | — | — |
| `project_annotation.archive` | `own` | — | — | — | — | — |
| `project_annotation.create` | `other` | — | — | — | — | — |
| `project_annotation.create` | `own` | A | A | A | A | — |
| `project_annotation.delete` | `other` | A | A | — | — | — |
| `project_annotation.delete` | `own` | A | A | A | A | — |
| `project_annotation.hide` | `other` | A | A | — | — | — |
| `project_annotation.hide` | `own` | — | — | — | — | — |
| `project_annotation.lock` | `other` | A | A | — | — | — |
| `project_annotation.lock` | `own` | — | — | — | — | — |
| `project_annotation.read` | `other` | A/R/F | A/R/F | A/R/F | A/R/F | A/R/F |
| `project_annotation.read` | `own` | A/R/F | A/R/F | A/R/F | A/R/F | A/R/F |
| `project_annotation.restore` | `other` | A | A | — | — | — |
| `project_annotation.restore` | `own` | A | A | A | A | — |
| `project_annotation.review` | `any` | A/R/F | A/R/F | — | — | — |
| `project_annotation.unlock` | `other` | A | A | — | — | — |
| `project_annotation.unlock` | `own` | — | — | — | — | — |
| `project_annotation.update` | `other` | — | — | — | — | — |
| `project_annotation.update` | `own` | A | A | A | A | — |
| `project_annotation_reply.create` | `other` | A | A | A | A | — |
| `project_annotation_reply.create` | `own` | A | A | A | A | — |
| `project_annotation_reply.delete` | `other` | — | — | — | — | — |
| `project_annotation_reply.delete` | `own` | A | A | A | A | — |
| `project_annotation_reply.restore` | `other` | — | — | — | — | — |
| `project_annotation_reply.restore` | `own` | A | A | A | A | — |
| `project_annotation_reply.update` | `other` | — | — | — | — | — |
| `project_annotation_reply.update` | `own` | A | A | A | A | — |
| `project_discussion.create` | `any` | A | A | A | A | — |
| `project_discussion.delete` | `other` | A | A | — | — | — |
| `project_discussion.delete` | `own` | A | A | A | A | — |
| `project_governance.read` | `any` | A/R/F | A/R/F | — | — | — |
| `project_item.manage` | `any` | A | A | A | — | — |
| `project_participation.join` | `open` | A | A | A | A | A |
| `project_participation.leave` | `open` | A | A | A | A | A |
| `project_participation.manage` | `managed` | A | A | — | — | — |
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
| `workspace_invitation.create` | `owner` | — | — | — | — | — |
| `workspace_invitation.read` | `any` | A/R | A/R | — | — | — |
| `workspace_invitation.revoke` | `any` | A | A | — | — | — |
| `workspace_maintenance.run` | `any` | A | A | — | — | — |
| `workspace_member.change_role` | `admin` | A | — | — | — | — |
| `workspace_member.change_role` | `member` | A | A | — | — | — |
| `workspace_member.change_role` | `owner` | — | — | — | — | — |
| `workspace_member.promote` | `admin` | — | — | — | — | — |
| `workspace_member.promote` | `member` | A | — | — | — | — |
| `workspace_member.promote` | `owner` | — | — | — | — | — |
| `workspace_member.reactivate` | `admin` | A | — | — | — | — |
| `workspace_member.reactivate` | `member` | A | A | — | — | — |
| `workspace_member.reactivate` | `owner` | — | — | — | — | — |
| `workspace_member.suspend` | `admin` | A | — | — | — | — |
| `workspace_member.suspend` | `member` | A | A | — | — | — |
| `workspace_member.suspend` | `owner` | — | — | — | — | — |
| `workspace_member.terminate` | `admin` | A | — | — | — | — |
| `workspace_member.terminate` | `member` | A | A | — | — | — |
| `workspace_member.terminate` | `owner` | — | — | — | — | — |
| `workspace_member.transfer_ownership` | `admin` | A | — | — | — | — |
| `workspace_member.transfer_ownership` | `member` | A | — | — | — | — |
| `workspace_member.transfer_ownership` | `owner` | — | — | — | — | — |
| `workspace_membership.read` | `any` | A/R | A/R | — | — | — |
