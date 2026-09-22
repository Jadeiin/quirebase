# Workspaces as data-governance and ACL boundaries

Status: proposed.

Quirebase introduces `Workspace` as the first-class data-governance, ACL, shared-library and
team-governance boundary between the Instance and Project layers. Workspace membership and
capabilities govern canonical Items, Documents, Tags and shared discussions; a Project remains a
Workspace-local research collaboration context and never grants or propagates Workspace Item
authority.

This decision supersedes the Item Owner authorization concept and the Project ownership,
Project Role and Project-membership-as-Item-access assumptions recorded in the domain glossary
and in the relevant portions of ADR 0011 and ADR 0004. Quirebase is alpha software, so this is a
forward-only model change with no compatibility layer for the previous assumptions.

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

The initial Workspace created during successful User provisioning is a normal Workspace with one
owner. “Personal Library” is a product label for this initial state, not a separate Workspace
kind or ACL mode. It may be renamed, shared, archived, restored, transferred or deleted using the
same rules as another Workspace.

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
| Create/update/archive Projects | yes | yes | yes | no | no |
| Manage Project membership | yes | yes | no | no | no |
| Write Item or Project Discussion/Notes | yes | yes | yes | yes | no |
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
- Successful User provisioning transactionally and idempotently creates the User's initial
  Workspace and owner membership.
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

The policy never blocks automatic creation of the initial Workspace during User provisioning.
Quota and rate limits are intentionally separate concerns.

A User with no active Workspace membership may still log in and use account-level operations, but
all Library, Project, Tag and Document operations fail with a typed membership-required error.
The system does not silently create another Personal Library; an explicit repair or create action
is required.

### Project is a collaboration context, not an ACL root

A Project belongs to exactly one Workspace and organizes a working set of Items plus Project-scoped
Annotations, Discussions and Notes. `Project.owner_id` is not retained as an authority field.
`created_by` is provenance only. Project lifecycle, metadata, membership and moderation are
controlled by Workspace capabilities.

`ProjectMember` contains participation information, such as `project_id`, `user_id`, `added_by`
and timestamps, but no role. It is a scope gate, not an authority grant:

- `visibility=workspace`: every active Workspace member may read the Project context. A Project
  may have no ProjectMember rows. Mutations require the caller's Workspace capability.
- `visibility=members`: an active ProjectMember is required to read or mutate the Project context;
  at least one active member is required for this visibility mode. Mutations still require the
  caller's Workspace capability.

Project membership never grants `items.edit`, `files.manage`, `items.delete`, Tag governance or
any other Workspace capability. ProjectItem means only “this Item is in this Project working
set”; it cannot create a durable Item access grant or be used to cross a Workspace boundary.

Project membership management is an owner/admin Workspace capability (`projects.members.manage`).
If delegation is needed later, it is represented by a capability grant rather than a Project role.

### Project-scoped content

Item Discussion is Workspace-scoped and is visible through Item access. Project Discussion and
Notes are Project-scoped and follow Project visibility plus the caller's Workspace capability.

Annotations have exactly two scopes:

- A private Annotation is visible and editable only by its author. Even a `viewer` may create and
  edit their own private Annotation.
- A Project Annotation is authored content in Project context and must bind to a `ProjectItem`,
  which proves that the Project contains the Item and both belong to the same Workspace. Editors
  and reviewers may create/edit their own Project Annotations when the Project scope gate and
  Workspace capability allow it.

Workspace owner/admin may moderate another author's Project Annotation through operations such as
hide, archive, lock, restore or delete. Moderation must not rewrite authored content or attribution.

### Lifecycle

Workspace and Project have `active`, `archived` and internal `deleted` lifecycle states.

An archived Workspace remains readable and exportable, including existing file downloads, but
rejects Item, file, Tag, Project, membership and shared Discussion mutations. Owner/admin may
restore it. Permanent Workspace deletion is owner-only and requires archive plus a retention
period; `deleted` is an internal cleanup state and is not exposed as an ordinary business state.

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
temporary, reason-required, fully audited and read-only by default. Write/delete break-glass
semantics require a later security decision; ordinary endpoints never infer this authority.

### Database invariants

Workspace-owned roots store `workspace_id`. Foreign keys, composite keys or equivalent database
constraints enforce lineage for ProjectItem, ItemTag, Project Annotation and other high-risk
associations. Service-layer checks provide typed errors and capability decisions, but the database
is the final boundary against cross-Workspace references.

The schema must also enforce one owner membership per Workspace, unique active membership identity,
Workspace-local Tag uniqueness such as `UNIQUE(workspace_id, normalized_name)`, and the invariant
that a members-visible Project cannot be left without an active ProjectMember.

## Consequences

- A single-team deployment remains simple: the automatically created initial Workspace can hide the
  Workspace selector while retaining the same explicit backend boundary.
- Item stewardship, file access, Tag governance, Discussions, Annotations and Agent context have
  one auditable root instead of inheriting accidental Project or creator semantics.
- Project membership can organize a working set and restrict Project context without becoming a
  hidden Item ACL propagation mechanism.
- The Access Module becomes the sole policy evaluator for Workspace roles and capabilities; Web,
  MCP, jobs and business Modules must call it rather than branch on role strings.
- Database lineage constraints, explicit Workspace context and finalizer re-authorization add
  schema and API surface, but prevent accidental cross-team references.
- Instance administrators can perform tenancy recovery without receiving silent research-data
  access; break-glass access is visible and reviewable.
- This is an alpha forward-only cutover. Existing instance-global ownership assumptions, Project
  roles and Project-derived Item grants are removed rather than adapted through compatibility
  aliases. Existing data is initialized under the current deployment's initial Workspace policy;
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
