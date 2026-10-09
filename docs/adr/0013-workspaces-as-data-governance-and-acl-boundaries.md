---
status: accepted
---

# Workspaces as data-governance and ACL boundaries

An instance-global Library conflates deployment, team governance and research-data ownership.
Quirebase makes Workspace the canonical governance, membership and authorization boundary, with
Project as a collaboration context inside one Workspace. An Item can belong to several Projects,
so one Workspace lineage and one resource-action policy keep its authority unambiguous while
allowing mutually untrusted teams to share an instance.

Membership, policy projections, Project participation, lifecycle, cross-Workspace flows, API context
and database invariants are defined in the
[Workspace governance contracts](../architecture/workspace-governance.md).

## Considered options

- **Keep Instance as the team boundary.** Rejected because one instance cannot safely host multiple
  mutually untrusted teams while retaining a coherent Tag, Item, Discussion and Agent context.
- **Make Project the security tenant.** Rejected because an Item may belong to multiple Projects;
  ProjectItem is an organizational association and cannot be the canonical Item ownership root.
- **Use Workspace as UI-only grouping.** Rejected because it leaves the existing implicit ACL and
  provenance ambiguity intact.
- **Preserve Item Owner or Project roles as a second authority path.** Rejected because creator or
  Project participation would again bypass Workspace governance and produce conflicting decisions.
- **Give instance administrators implicit content access.** Rejected because tenancy governance and
  research-data access have different audit and least-privilege requirements.
- **Introduce live cross-Workspace sharing now.** Rejected because its lifecycle, revocation and
  audit semantics require an explicit share resource rather than weakened ordinary foreign keys.

## Consequences

- All Workspaces use the same domain rules and have exactly one active owner. User provisioning
  creates an ordinary Workspace; a single-Workspace UI may de-emphasize the selector.
- Active Workspace membership and the Access Module's resource-action policy govern canonical
  data. Project participation controls the working context and managed-Project discovery without
  creating Item grants or another role axis; `created_by` remains provenance.
- Instance administrators may freeze governance without receiving implicit content access.
  Exceptional inspection is explicit, reason-bound, read-only and audited.
- Database lineage constraints, explicit Workspace context and durable finalizer re-authorization
  add schema and API surface but prevent cross-team references and use of revoked authority.
- This supersedes Item Owner authorization and the Project ownership, roles and Item-access
  assumptions in [ADR 0004](0004-research-intelligence-mcp-and-agent.md) and
  [ADR 0011](0011-unified-business-concurrency.md).
- The alpha cutover removes previous ownership assumptions and Project-derived Item grants without
  compatibility aliases. Live sharing, quota and large-scale migration policy remain separate work.
