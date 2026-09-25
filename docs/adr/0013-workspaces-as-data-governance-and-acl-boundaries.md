# Workspaces as data-governance and ACL boundaries

Status: accepted.

Quirebase introduces `Workspace` as the first-class data-governance, ACL, shared-library and
team-governance boundary between the Instance and Project layers. Workspace membership and
capabilities govern canonical Items, Documents, Tags and shared discussions; a Project remains a
Workspace-local research collaboration context and never grants or propagates Workspace Item
authority.

This decision supersedes the Item Owner authorization concept and the Project ownership, Project
Role and Project-membership-as-Item-access assumptions recorded in the domain glossary and in the
relevant portions of ADR 0011 and ADR 0004. Project `created_by` is provenance only; Projects have
no owner or ownership-transfer operation. Quirebase is alpha software, so this is a forward-only
model change with no compatibility layer for the previous assumptions.

## Context

The instance-global library model conflates deployment, team governance and data ownership. It
also makes Project membership carry more meaning than a research working set: membership can be
mistaken for Item access, while an Item shared by several Projects remains one canonical object.
Tags, Discussions, Annotations and Agent/API requests lack one explicit governance root, and
`created_by` fields are easily misread as durable ownership.

Quirebase needs to host multiple teams that may not trust one another while preserving a simple
single-team deployment. The boundary must therefore be explicit in the domain model, enforced by
database lineage and available to Web, API, MCP and durable workflow callers.

## Decision

### Workspace is the governance root

The resource hierarchy is:

```text
Instance
├── User / Authentication / System Role
├── Workspace
│   ├── Workspace Members
│   ├── canonical Item Library
│   ├── File Revisions and Attachments
│   ├── shared Tags
│   ├── Item Discussions
│   └── Projects
│       ├── Project Members (no role)
│       ├── ProjectItems
│       ├── Project Annotations
│       └── Project Discussions and Notes
└── instance-global configuration, provider cache and workflow infrastructure
```

Every Workspace-owned aggregate has one `workspace_id` lineage. Active Workspace membership is
required for Workspace data access. By default, an active Workspace member can read and download
the Workspace Item Library, including canonical Item metadata, File Revisions, Attachments and
Item Discussions. A suspended or terminated membership has no effective access; it does not alter
resource provenance.

All Workspaces have the same domain and authorization semantics, regardless of whether one is
created during User provisioning or later. There is no personal/shared Workspace kind or ACL mode.
Each Workspace may be renamed, shared, archived, restored, transferred or deleted using the same
rules.

### Workspace roles and capabilities

Workspace is the only persistent resource role axis. The roles are `owner`, `admin`, `editor`,
`reviewer` and `viewer`; business code asks the Access Module to evaluate capabilities and never
branches directly on a role string. The capability namespace is extensible and may be refined in
later decisions, but authorization always evaluates Workspace lineage and active membership before
the requested capability.

The initial role presets are:

| Capability family | Owner | Admin | Editor | Reviewer | Viewer |
| --- | ---: | ---: | ---: | ---: | ---: |
| Read/download Workspace data | yes | yes | yes | yes | yes |
| Create/edit canonical Item metadata | yes | yes | yes | no | no |
| Upload/manage File Revisions and Attachments | yes | yes | yes | no | no |
| Create/attach/detach Tags | yes | yes | yes | no | no |
| Rename/merge/delete shared Tags | yes | yes | no | no | no |
| Manage shared Citation Styles | yes | yes | yes | no | no |
| Create Workspace/open Projects | yes | yes | yes | no | no |
| Create managed Projects | yes | yes | no | no | no |
| Update/archive existing Projects | yes | yes | yes | no | no |
| Manage managed-Project participation | yes | yes | no | no | no |
| Write Item or Project Discussion/Notes | yes | yes | yes | yes | no |
| Moderate another author's Item or Project Discussion | yes | yes | no | no | no |
| Create/edit own private or Project Annotation | yes | yes | yes | yes | private only |
| Moderate another author's Annotation | yes | yes | no | no | no |
| Permanently delete shared Items or Documents | yes | yes | no | no | no |
| Manage Workspace members, roles and settings | yes | yes | no | no | no |
| Transfer Workspace ownership or manage admins | yes | no | no | no | no |
| Archive/restore Workspace | yes | yes | no | no | no |
| Permanently delete Workspace | yes | no | no | no | no |

The exact capability constants remain an Access Module concern. A later decision may split or add
capabilities, but it must not create a second Project role axis or infer authority from `created_by`.

`System Role=administrator` is instance-level tenancy and lifecycle governance. It does not make
the administrator an implicit Workspace member or grant content access. An administrator may use
normal membership, or an explicit temporary break-glass operation, when content access is needed.

### User provisioning, Workspace creation and membership

Instance registration and Workspace admission are separate operations:

- The existing instance-level `Invitation` is responsible for provisioning/registering a User,
  subject to instance open/closed registration and administrator-controlled manual creation.
- Each successful User creation transaction also creates one ordinary Workspace and its owner
  membership. Registration retries cannot create a second User because the registration identity
  is unique; existing Users are never provisioned implicitly.
- Admission to another Workspace uses a separate `WorkspaceInvitation` or an owner/admin
  membership mutation for an existing User.
- A valid membership has state `active` or `suspended`. Removal terminates the membership and is
  retained as an audit/history record, not as an ACL-satisfying `removed` state.
- Workspace owner/admin manages ordinary membership. An instance administrator may perform only
  coarse tenancy/lifecycle governance such as suspension or recovery, not ordinary content access.
- Ownership transfer is required before an owner can leave, be suspended or be removed. Each
  active Workspace has exactly one authoritative owner and an owner membership.

Additional Workspace creation is controlled by instance-level `workspace_creation_policy`:

- `admins_only`: only instance administrators create additional Workspaces;
- `members_allowed`: any active User may create one and becomes its owner.

Under `admins_only`, the administrator must specify an active Workspace owner by exact username.
The administrator is not added as a Workspace member unless explicitly selected as that owner;
Workspace creation does not grant instance administrators implicit content access. The lookup is
exact and does not expose a browsable instance-wide user directory.

The policy never blocks creation of an ordinary Workspace as part of User provisioning.
Quota and rate limits are intentionally separate concerns.

A User with no active Workspace membership may still log in and use account-level operations, but
all Library, Project, Tag and Document operations fail with a typed membership-required error.
The system does not silently create another Workspace or repair membership. A new Workspace may
be created only through the ordinary creation policy; membership restoration and ownership changes
use their explicit governance operations. User records do not store an active Workspace pointer or
provisioning state.

### Project is a working context, not an ACL root

A Project belongs to exactly one Workspace and organizes a working set of Items plus Project-scoped
Annotations, Discussions and Notes. A Project has no owner field or ownership-transfer operation;
`created_by` is provenance only. Project lifecycle, metadata, participation and moderation are
controlled by Workspace capabilities.

The Project `visibility` field defines Project discoverability and participation policy. It does
not create another role or Workspace capability. `ProjectMember` is a role-less association
recording a User's selected working context; it grants no Workspace capability and never grants
access to canonical Workspace Items:

- `visibility=workspace`: every active Workspace member can discover the Project and participates
  implicitly. The Project has no ProjectMember associations and offers no join, leave or
  member-management operations. Users with `projects.create` may create one.
- `visibility=open`: every active Workspace member can discover the Project and may choose to join
  or leave. Creating or switching to this mode enrolls the actor as a participant. Users with
  `projects.create` may create one.
- `visibility=managed`: only ProjectMembers and Workspace owners/admins can discover the Project and
  its Project-scoped content. Members cannot self-join or leave; Workspace owners/admins curate
  participation with `projects.members.manage`. Only users with `projects.create_managed` may
  create one, and a new managed Project starts with zero participants.

Switching to `workspace` removes ProjectMember associations in the same transaction. Switching
between `open` and `managed` preserves selected participants; transitioning from `workspace` to
`open` enrolls the actor, while transitioning to `managed` does not. An empty participant list is
valid for `open` and `managed`. No Project has an owner, ownership transfer, or minimum-member
invariant. Workspace membership and capabilities remain the authorization boundary for canonical
Workspace data and Project mutations; ProjectMember affects only managed Project discoverability.

Project membership never grants `items.read`, `items.edit`, `files.manage`, `items.delete`, Tag
governance or any other Workspace capability. ProjectItem means only “this Item is in this Project
working set”; it cannot create a durable Item access grant or be used to cross a Workspace
boundary. Canonical Items remain accessible according to Workspace membership and capabilities,
even when their association with a managed Project is hidden.

Managing participation for an active managed Project is an owner/admin Workspace capability
(`projects.members.manage`). Open Projects allow self-service participation, while Workspace
Projects have no ProjectMember lifecycle. If delegation is needed later, it is represented by a
capability grant rather than a Project role.

No Project creator or participant must transfer ownership before leaving, suspension, termination
or account deactivation. Those lifecycle operations remain governed by Workspace membership and
the independent Workspace-owner invariant; ProjectMember associations are removed or become
inactive as appropriate without preserving a minimum participant count.

### Project-scoped content

Item Discussion is Workspace-scoped and is visible through Item access. Project Discussion, Notes
and Project Annotations are Project-scoped: `workspace` and `open` Projects are visible to all
active Workspace members, while managed Project content is visible only to ProjectMembers and
Workspace owners/admins. Mutations still require the caller's Workspace capability, and
participation never grants that capability.

Discussion authors may delete their own messages when `discussion.write` is effective. Workspace
owners and admins have a separate `discussion.moderate` capability to remove another author's Item
or Project Discussion message with a required reason and an audit event. Project moderation follows
Project lineage and lifecycle rules; governors can reach managed Project content without becoming
ProjectMembers. Moderation does not rewrite authored content or attribution. An instance
administrator has no implicit Discussion moderation authority, and read-only break-glass cannot
perform a moderation mutation.

Annotations have exactly two scopes:

- A private Annotation is visible and editable only by its author. Even a `viewer` may create and
  edit their own private Annotation.
- A Project Annotation is authored content in Project context and must bind to a `ProjectItem`,
  which proves that the Project contains the Item and both belong to the same Workspace. Editors
  and reviewers may create/edit their own Project Annotations when Workspace membership and
  capability allow it.

Workspace owner/admin may moderate another author's Project Annotation through operations such as
hide, archive, lock, restore or delete. Moderation must not rewrite authored content or attribution.

### Lifecycle

Workspace and Project have `active`, `archived` and internal `deleted` lifecycle states.

An archived Workspace remains readable and exportable, including existing file downloads, but
rejects Item, file, Tag, Project, membership and shared Discussion mutations. Owner/admin may
restore it. Permanent Workspace deletion is owner-only and requires archive plus a retention
period (30 days by default). The deletion transaction removes the Workspace root and cascades
its owned rows; a durable, reference-aware cleanup removes its stored objects. Audit Events keep
the deleted Workspace ID as historical metadata. `deleted` is an internal cleanup state and is
not exposed as an ordinary business state.

An archived Project is readable but rejects ProjectItem, Annotation, Discussion, Notes and
membership mutations. Project archive/restore is controlled by the Workspace `projects.manage`
capability and does not archive or remove its Workspace Items. Permanent Item deletion is limited
to Workspace owner/admin capability. Instance administrators have no implicit delete authority;
recovery or break-glass writes are explicit, temporary and fully audited.

### Cross-Workspace data flows

Ordinary relations cannot cross Workspaces. In particular, a ProjectItem, ItemTag or Project
Annotation must have matching Workspace lineage. Cross-Workspace `copy` and `import` create new
canonical resources in the destination Workspace and never create live ACL links. `export` uses
source read/export authority; import re-checks the destination create capability. Every such
operation records actor, source and destination Workspace IDs and the resource ID mapping in an
Audit Event. A future live-sharing model requires a separate decision and explicit share resource.

Instance-global resources may include User/authentication, system/provider configuration, external
bibliographic metadata cache and workflow infrastructure. Audit Events are instance-global records,
but Workspace resource events carry `workspace_id` and optional `project_id` context. Audit metadata
records action, target IDs, capability/authorization result, source and time; it does not copy full
Item or Annotation content.

### API, Agent and durable workflow context

API Tokens remain User-scoped. Every API, MCP and durable command carries an explicit
`workspace_id`; a Project operation also validates `project.workspace_id` against that context.
The backend may store an active Workspace preference in the UI, but authorization never derives
from implicit session state. Deep links contain enough context to resolve their Workspace
independently.

Durable workflows persist actor, Workspace ID, Project ID where relevant and target resource IDs.
After external work, the finalizer re-reads canonical resources and re-evaluates Workspace
membership/capability before committing. A stale or terminated grant rejects finalization rather
than inheriting request-time authority.

Instance administrators may invoke only an explicit `workspace.break_glass` operation. It is
temporary, reason-required, fully audited and read-only in the current contract. Write/delete break-glass
semantics require a later security decision; ordinary endpoints never infer this authority.

### Database invariants

Workspace-owned roots store `workspace_id`. Foreign keys, composite keys or equivalent database
constraints enforce lineage for ProjectItem, ItemTag, Project Annotation and other high-risk
associations. Service-layer checks provide typed errors and capability decisions, but the database
is the final boundary against cross-Workspace references.

The schema must also enforce one owner membership per Workspace, unique active membership identity
and Workspace-local Tag uniqueness such as `UNIQUE(workspace_id, normalized_name)`. Projects have no
owner invariant. The schema must not materialize implicit Workspace-wide participation or require
a minimum ProjectMember count.

## Consequences

- A single-team deployment remains simple: when a User has one accessible Workspace, the UI may
  de-emphasize the selector while retaining the same explicit backend boundary.
- Item stewardship, file access, Tag governance, Discussions, Annotations and Agent context have
  one auditable root instead of inheriting accidental Project or creator semantics.
- Project membership records selected working contexts only. Workspace-wide participation remains
  implicit, open participation is self-service, and managed participation is private-like and
  explicitly curated. Managed membership exposes Project-scoped content but does not create
  canonical Item grants or Workspace capabilities.
- Project creators are recorded only as provenance. Workspace governance—not Project ownership—
  maintains managed participation and Project lifecycle.
- The Access Module becomes the sole policy evaluator for Workspace roles and capabilities; Web,
  MCP, jobs and business Modules must call it rather than branch on role strings.
- Database lineage constraints, explicit Workspace context and finalizer re-authorization add
  schema and API surface, but prevent accidental cross-team references.
- Instance administrators can perform tenancy recovery without receiving silent research-data
  access; break-glass access is visible and reviewable.
- This is an alpha forward-only cutover. Existing instance-global ownership assumptions, Project
  roles and Project-derived Item grants are removed rather than adapted through compatibility
  aliases. Existing data is initialized under the current deployment's Workspace policy;
  quota and large-scale migration policy are separate work.

## Rejected alternatives

- **Keep Instance as the team boundary.** Rejected because one instance cannot safely host multiple
  mutually untrusted teams while retaining a coherent Tag, Item, Discussion and Agent context.
- **Make Project the security tenant.** Rejected because an Item may belong to multiple Projects;
  ProjectItem is an organizational association and cannot be the canonical Item ownership root.
- **Use Workspace as UI-only grouping.** Rejected because it leaves the existing implicit ACL and
  provenance ambiguity intact.
- **Preserve Item Owner or Project roles as a second authority path.** Rejected because creator or
  Project membership would again bypass Workspace governance and produce conflicting decisions.
- **Give instance administrators implicit content access.** Rejected because tenancy governance and
  research-data access have different audit and least-privilege requirements.
- **Introduce live cross-Workspace sharing now.** Rejected because its lifecycle, revocation and
  audit semantics require an explicit share resource rather than weakened ordinary foreign keys.
