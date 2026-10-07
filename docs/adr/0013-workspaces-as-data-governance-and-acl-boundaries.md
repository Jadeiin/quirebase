# Workspaces as data-governance and ACL boundaries

Status: accepted.

Quirebase introduces `Workspace` as the first-class data-governance, ACL, shared-library and
team-governance boundary between the Instance and Project layers. Workspace membership and
resource-action decisions govern canonical Items, Documents, Tags and shared discussions; a
Project remains a Workspace-local research collaboration context and never grants or propagates
Workspace Item authority.

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

Ordinary Workspace-scoped HTTP endpoints return the same `workspace_unavailable` 404, with no
membership detail, when the root is missing/deleted or the caller has no active membership.
This prevents Workspace existence from becoming observable through an authorization failure.
An authenticated active member lacking a resource-action capability receives `permission_denied`
403; invalid credentials still receive 401. Internal membership exceptions remain distinct for
workflow revocation handling. The browser refreshes its accessible Workspace list and recovers
through the chooser when its current URL context becomes unavailable.

All Workspaces have the same domain and authorization semantics, regardless of whether one is
created during User provisioning or later. There is no personal/shared Workspace kind or ACL mode.
Each Workspace may be renamed, shared, archived, restored, transferred or deleted using the same
rules.

### Roles and resource-action decisions

Workspace is the only persistent resource role axis. The roles are `owner`, `admin`, `editor`,
`reviewer` and `viewer`; business code asks the Access Module for one decision and never branches
directly on a role string. Casbin is the sole resource-action capability policy evaluator for
Workspace and System authority. Domain scope, participation, lineage and lifecycle invariants
remain explicit domain rules.
Every authorization decision has the same shape:

```text
subject + resource + action + lifecycle + relation -> allow | deny
```

The subject is a persistent role projected as `workspace:<role>` or `system:<role>`. Resources are
domain names such as `item`, `project`, `workspace_member` or `project_annotation`; actions are
verbs such as `update`, `manage`, `suspend` or `hide`. An action never repeats its resource name.
Lifecycle represents Workspace governance state, and relation carries canonical request facts such
as `own`, `other`, `member`, `admin` or `managed`; `any` means the decision does not depend on a
target relation.

Business Modules load lineage, membership, lifecycle, authorship and participation from the
database, retain the locks and constraints required for concurrent correctness, then invoke that
single Access decision. They must not add a coarse Workspace-wide gate before a more specific
resource decision. The canonical dotted form such as `item.update` is used only to serialize a
`resource=item`, `action=update` pair in API projections and Audit Events. Frontend code receives
server-authored capability sets and asks `can(action)`. The `allowed` set contains resolved
resource-action grants. Choices are projected on their domain read models rather than through a
public policy language: `WorkspaceView.allowed_project_participations` lists Project creation
modes, and `ProjectView.allowed_participation_changes` lists permitted target modes for that
Project. A choice-constrained action such as `project.create` is absent from `allowed`; creation
uses the concrete choice list. Metadata-update capability and participation choices remain
independent. Frontend code never maps roles to actions.

Actions use one controlled vocabulary. Ordinary persistence operations use `create`, `read`,
`update` and `delete`; `read` covers both collection and individual retrieval at the policy layer.
Lifecycle and domain commands retain precise verbs such as `archive`, `restore`, `suspend`,
`revoke`, `join` or `transfer_ownership`. `manage` is reserved for an intentionally indivisible
family of subordinate mutations. Authorship or moderation does not create action aliases: the same
`delete` or `restore` action is evaluated with `relation=own` or `relation=other`.
Command variants also remain relations rather than action suffixes: Project participation constrains
`project.create`, and the configured creation mode constrains `workspace.create`. When a client
must choose among such variants, the server projects concrete choices on the domain read model.
Casbin relations remain internal to the Access Module. `WorkspaceView.allowed_invitation_roles` lists the roles the caller may invite;
the frontend does not translate invitation roles into Casbin's `admin` or `member` classes.
`WorkspaceGovernanceMemberView.allowed_roles` similarly lists concrete role transitions for that
target, including promotion, while its decision set contains lifecycle and ownership actions.
Item metadata, files, Tags and ProjectItem capabilities are projected independently; metadata-edit
authority is not a prerequisite for those subordinate operations. Reindex uses the separate
`workspace_maintenance.run` decision at dispatch and at every durable batch.

The initial role presets are:

| Resource-action family | Owner | Admin | Editor | Reviewer | Viewer |
| --- | ---: | ---: | ---: | ---: | ---: |
| Read/download Workspace data | yes | yes | yes | yes | yes |
| Create/copy/update canonical Item metadata | yes | yes | yes | no | no |
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
| Create/update own private or Project Annotation | yes | yes | yes | yes | private only |
| Moderate another author's Annotation | yes | yes | no | no | no |
| Permanently delete shared Items | yes | yes | no | no | no |
| Permanently delete Documents | yes | yes | yes | no | no |
| Manage Workspace members, roles and settings | yes | yes | no | no | no |
| Rebuild Workspace search projections | yes | yes | no | no | no |
| Transfer Workspace ownership or manage admins | yes | no | no | no | no |
| Archive/restore Workspace | yes | yes | no | no | no |
| Permanently delete Workspace | yes | no | no | no | no |

The exact resource and action constants remain an Access Module concern. A later decision may split
or add decisions, but it must not introduce another capability namespace, duplicate coarse and
fine-grained gates, create a second Project role axis or infer authority from `created_by`.

`System Role=administrator` is instance-level tenancy and lifecycle governance. It does not make
the administrator an implicit Workspace member or grant content access. An administrator may use
normal membership, or an explicit one-request break-glass inspection, when content access is needed.

Instance governance provides administrative freeze/unfreeze and reason-bound read-only inspection.
It does not repair missing or inactive Workspace ownership. Integrity checks diagnose those
conditions; an owner-repair command would require a separate, narrowly scoped, audited decision
and would not grant ordinary content access.

### User provisioning, Workspace creation and membership

Instance registration and Workspace admission are separate operations:

- The existing instance-level `Invitation` is responsible for provisioning/registering a User,
  subject to instance open/closed registration and administrator-controlled manual creation.
- Each successful User creation transaction also creates one ordinary Workspace and its owner
  membership. Registration retries cannot create a second User because the registration identity
  is unique; existing Users are never provisioned implicitly.
- Admission to another Workspace uses a separate `WorkspaceInvitation` or an owner/admin
  membership mutation for an existing User.
- Both invitation types resolve through the public `/invitations/{token}` API with an explicit
  `kind` discriminator and share the browser entry `/invite/{token}`. Acceptance remains two
  distinct commands: `POST /invitations/{token}/accept` provisions an account, while
  `POST /workspace-invitations/{token}/accept` admits an existing User. Workspace admission still
  accepts only the invited existing User; the UI
  keeps the invitation open while switching away from a different signed-in account.
- A valid membership has state `active` or `suspended`. Removal terminates the membership and is
  retained as an audit/history record, not as an ACL-satisfying `removed` state.
- Workspace owner/admin manages ordinary membership. An instance administrator may perform only
  coarse lifecycle governance such as freeze/unfreeze, not ordinary content access.
- The active member directory exposes Workspace roles as collaboration metadata, requiring both
  an active User account and an active current Workspace membership. The governance view retains
  current memberships for inactive accounts and adds membership identifiers, state, join time,
  concrete allowed role choices and member-specific lifecycle decisions for owners/admins.
  The active directory requires `workspace.read`; the governance view requires
  `workspace_membership.read`. Role choices omit the current role while commands remain idempotent.
- Ownership transfer is required before an owner can leave, be suspended or be removed. Each
  surviving Workspace has exactly one active authoritative owner membership. Transfer promotes
  the new owner to `owner` and changes the previous owner to `admin` in the same transaction.

Additional Workspace creation is controlled by instance-level `workspace_creation_policy`:

- `admins_only`: only instance administrators create additional Workspaces;
- `members_allowed`: any active User may create one and becomes its owner.

Under `admins_only`, the administrator must specify an active Workspace owner by exact username.
The administrator is not added as a Workspace member unless explicitly selected as that owner;
Workspace creation does not grant instance administrators implicit content access. The lookup is
exact and does not expose a browsable instance-wide user directory.
The creation Audit Event records the actor's authorizing System role. Its detail records the selected
owner, the resulting owner Workspace role and the instance creation policy.

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
controlled by Workspace resource-action decisions.

The Project `participation` field defines Project discoverability and participation policy. It does
not create another role or authorization axis. HTTP creation requires an explicit participation
choice. The creation form and default persistence/domain construction select `open`; Workspace-wide
implicit participation must be selected deliberately. `ProjectMember` is a role-less association
recording a User's selected working context; it grants no Workspace authority and never grants
access to canonical Workspace Items:

- `participation=workspace`: every active Workspace member can discover the Project and participates
  implicitly. The Project has no ProjectMember associations and offers no join, leave or
  member-management operations. Users with `project.create` may create one.
- `participation=open`: every active Workspace member can discover the Project and may choose to join
  or leave. Creating an open Project, or switching from `workspace` to `open`, enrolls the actor
  as a participant. Switching from `managed` preserves the selected participants. Users with
  `project.create` may create one.
- `participation=managed`: only ProjectMembers and Workspace owners/admins can discover the Project and
  its Project-scoped content. Members cannot self-join or leave; Workspace owners/admins curate
  participation with `project_membership.manage`. Only users allowed `project.create` with
  `relation=managed` may create one, and a new managed Project starts with zero participants.

Ordinary discovery is fixed domain behavior: active Workspace members discover `workspace` and
`open` Projects, and explicit participants discover `managed` Projects. Casbin cannot redefine
those modes. The narrow `project_governance.read` decision adds discovery of managed Projects
for governance; the initial policy grants it to owners/admins, including read-only lifecycle states.
Collection, direct-link and locked reads share one SQL discovery predicate. Mutation loaders
filter undiscoverable roots before locking and recheck discoverability in a fresh statement after acquiring
the Project lock, including after waiting behind participant removal.

Read models call implicit or explicit participation `is_participating`; the existence of a
ProjectMember row is a different fact. Dashboard and personal Project lists include only
participating Projects. Managed Projects visible solely for governance stay in the directory
and governance surfaces, rather than entering the governor's personal working context.

Project detail exposes `active_participants`, a list of active Users with active Workspace
memberships and explicit selections. It is empty for implicit Workspace participation and omits
retained selections of suspended members or inactive Users. Managed participation commands use
`POST /projects/{id}/participants` and `DELETE /projects/{id}/participants/{user_id}`; the
persisted ProjectMember association remains a working-context selection, not an ACL membership.

Project settings use one partial `PATCH /projects/{id}` command and one transaction. Omitted
fields stay unchanged; metadata-only updates do not alter participation or ProjectMember rows.
Participation changes are an explicit submitted field with their own capability check.

Switching to `workspace` removes all ProjectMember associations in the same transaction, including
those belonging to suspended Workspace members. The UI confirms this permanent loss of participant
selection before submitting; switching back does not restore it. Switching
between `open` and `managed` preserves selected participants; transitioning from `workspace` to
`open` enrolls the actor, while transitioning to `managed` does not. Managed-Project participant
selection uses the active Workspace member directory and omits existing participants. An empty
participant list is valid for `open` and `managed`. No Project has an owner, ownership transfer, or
minimum-member invariant. Workspace membership and resource-action policy remain the authorization boundary for
canonical Workspace data and Project mutations; ProjectMember affects only managed Project
discoverability.

Item organization shows already assigned Projects, Workspace Projects and joined Projects by
default. Other open Projects and managed Projects visible through governance are expandable
choices. This is a working-context filter, not an authority restriction: a permitted caller can
still assign an Item to an open Project without joining it.

Project membership never grants `item.read`, `item.update`, `file.manage`, `item.delete`, Tag
governance or any other Workspace authority. ProjectItem means only “this Item is in this Project
working set”; it cannot create a durable Item access grant or be used to cross a Workspace
boundary. Canonical Items remain accessible according to Workspace membership and policy,
even when their association with a managed Project is hidden.

Managing participation for an active managed Project is an owner/admin decision
(`resource=project_membership`, `action=manage`, `relation=managed`). Open Projects allow
self-service participation, while Workspace Projects have no ProjectMember lifecycle. If
delegation is needed later, it is represented by a resource-action policy grant rather than a
Project role.

No Project creator or participant must transfer ownership before leaving, suspension, termination
or account deactivation. Those lifecycle operations remain governed by Workspace membership and
the independent Workspace-owner invariant; ProjectMember associations are removed or become
inactive as appropriate without preserving a minimum participant count. Suspending a Workspace
member retains their ProjectMember rows but makes participation ineffective because Workspace
access is denied. Reactivation restores their prior participation. Termination deletes those
rows; later Workspace admission does not restore old open or managed participation.

### Project-scoped content

Item Discussion is Workspace-scoped and is visible through Item access. Project Discussion, Notes
and Project Annotations are Project-scoped: `workspace` and `open` Projects are visible to all
active Workspace members, while managed Project content is visible only to ProjectMembers and
Workspace owners/admins. Mutations still require the caller's Workspace resource-action decision,
and participation never grants that authority.

Discussion authors may delete their own messages when the corresponding `item_discussion.delete`
or `project_discussion.delete` decision is effective with `relation=own`. Workspace owners and
admins may perform `delete` with `relation=other` on another author's Item or Project Discussion
message through a reason-required moderation operation with an audit event. Project moderation follows
Project lineage and lifecycle rules; governors can reach managed Project content without becoming
ProjectMembers. Moderation does not rewrite authored content or attribution. An instance
administrator has no implicit Discussion moderation authority, and read-only break-glass cannot
perform a moderation mutation.

Annotations have exactly two scopes:

- A private Annotation is visible and updatable only by its author. Even a `viewer` may create and
  update their own private Annotation.
- A Project Annotation is authored content in Project context and must bind to a `ProjectItem`,
  which proves that the Project contains the Item and both belong to the same Workspace. Editors
  and reviewers may create/update their own Project Annotations when Workspace membership and the
  corresponding resource-action decision allow it.

Workspace owner/admin may moderate another author's Project Annotation through operations such as
hide, archive, lock, restore or delete. Moderation must not rewrite authored content or attribution.

### Lifecycle

Workspace and Project have `active`, `archived` and internal `deleted` lifecycle states.

An archived Workspace remains readable and exportable, including existing file downloads, but
rejects Item, file, Tag, Project, membership and shared Discussion mutations. Owner/admin may
restore it. Permanent Workspace deletion is owner-only and requires archive plus a retention
period (30 days by default). The deletion transaction removes the Workspace root and cascades
its owned rows; a durable, reference-aware cleanup removes its stored objects. Audit Events keep
the deleted Workspace and Project IDs as historical metadata, without live-resource foreign keys.
`deleted` is an internal cleanup state and is
not exposed as an ordinary business state.

Archived Workspace governance member and invitation lists remain readable to owners/admins;
their mutations remain disabled.

An instance administrator may impose an administrative read-only freeze through
`governance_frozen_at` and `governance_frozen_by`. This is an overlay on Workspace state,
not a tenancy shutdown or a WorkspaceMember suspension. Active members retain content reads,
downloads and exports, while all Workspace mutations, ownership transfers, member and invitation
governance reads, restore and permanent deletion are blocked. Memberships and Project participation
are preserved. Only an instance administrator may unfreeze the Workspace by clearing the overlay;
unfreezing preserves its underlying active/archived state and archive retention timestamp. An
administrator gains no implicit content access by freezing or unfreezing a Workspace.

Archive is member-controlled preservation with owner/admin governance reads and restoration;
the administrative freeze reserves unfreezing to instance governance. Suspending an individual
WorkspaceMember instead removes that member's effective content access.

An archived Project is readable but rejects ProjectItem, Annotation, Discussion, Notes and
participation mutations. Project archive/restore is controlled by separate `project.archive` and
`project.restore` decisions and does not archive or remove its Workspace Items. Permanent Item
deletion is limited to the `item.delete` decision. Instance administrators have no implicit delete
authority. The current break-glass inspection grants no mutation authority.

Project deletion has no archive prerequisite: a caller allowed `project.delete` confirms the
current Project name before an active or archived Project enters internal `deleted` state.
This removes the Project working context, not its canonical Workspace Items. Workspace permanent
deletion retains its stronger archive and retention requirements.

Project archive/restore, Workspace-member suspend/reactivate and role setting, invitation revoke,
and instance governance freeze/unfreeze tolerate retries after reaching the requested state.
They still acquire their roots and recheck current authority before returning success; a repeat
does not change timestamps or add an Audit Event. Invitation revocation also leaves an already
expired invitation unchanged. Accepted invitations and terminated memberships remain unavailable
to these commands. Workspace archive/restore retain their lifecycle-specific capability checks.

### Cross-Workspace data flows

Ordinary relations cannot cross Workspaces. In particular, a ProjectItem, ItemTag or Project
Annotation must have matching Workspace lineage. Cross-Workspace `copy` and `import` create new
canonical resources in the destination Workspace and never create live ACL links. Copy requires
the source `workspace.export` decision and re-checks the destination `item.create` decision; other
import flows use `item.create`. Every such operation records actor, source and destination
Workspace IDs and the resource ID mapping in an Audit Event. A future live-sharing model requires
a separate decision and explicit share resource.

Item copy selectors receive only destinations currently satisfying both copy decisions, rather
than unusable options with empty grants. This read model is a hint; the copy command rechecks
current source and destination authority before committing.

Instance-global resources may include User/authentication, system/provider configuration, external
bibliographic metadata cache and workflow infrastructure. Audit Events are instance-global records,
but Workspace resource events carry `workspace_id` and optional `project_id` context. Audit metadata
records action, target IDs, the canonical authorizing resource-action key, source and time; it does
not copy full Item or Annotation content.

Inbound adapters bind Audit provenance for the invocation. HTTP includes both Login Session and
Bearer requests; MCP preserves its protocol and operation through the HTTP adapter. Domain services
do not select a transport source. Break-glass remains identified by its action and reason, while
`source` records the invoking protocol; calls without an adapter context use `internal`.

### API, Agent and durable workflow context

API Tokens remain User-scoped. Every API, MCP and durable command carries an explicit
`workspace_id`; a Project operation also validates `project.workspace_id` against that context.
The backend may store an active Workspace preference in the UI, but authorization never derives
from implicit session state. Deep links contain enough context to resolve their Workspace
independently.

Durable workflows persist actor, Workspace ID, Project ID where relevant and target resource IDs.
After external work, the finalizer re-reads canonical resources and re-evaluates Workspace
membership and the concrete resource-action decision before committing. A stale or terminated
grant rejects finalization rather than inheriting request-time authority. Project-scoped mutation
callers explicitly choose a shared or exclusive Project root lock; action metadata never silently
chooses a Project lock or upgrades it. Root locks precede cascading child-row locks.

Instance administrators may invoke only the explicit `resource=workspace_break_glass`,
`action=read` decision. It performs one reason-required, fully audited, read-only inspection of
at most 100 Items. It does not create a grant, reusable session or lease, and has no grant expiry
or revocation protocol.
Write/delete break-glass semantics require a later security decision; ordinary
endpoints never infer this authority.

### Database invariants

Workspace-owned roots store `workspace_id`. Foreign keys, composite keys or equivalent database
constraints enforce lineage for ProjectItem, ItemTag, Project Annotation and other high-risk
associations. Service-layer checks provide typed errors and authorization decisions, but the database
is the final boundary against cross-Workspace references.

Partial unique indexes enforce at most one current owner membership per Workspace and at most
one current membership per Workspace/User pair. Current means `terminated_at IS NULL`, including
suspended memberships. A row CHECK requires every owner membership to be active and non-terminated;
the database does not enforce the existence of an owner or the owner's account activity.
Service transactions preserve exactly one active owner for every surviving Workspace through
provisioning, atomic ownership transfer and prohibitions on owner suspension, termination and account
deactivation; `workspace_owner_ids()` validates owner membership and account activity on reads in
the same snapshot as Workspace existence. A concurrently deleted root is omitted, while an invalid
surviving root is an integrity failure. `doctor` diagnoses missing or invalid owners and Project
participation drift: Workspace-mode Projects must have no ProjectMember rows, and each explicit
participant must have a current membership in the same Workspace. Suspended memberships and
inactive accounts may retain participation for recovery; terminated memberships may not.
Workspace-local Tag
uniqueness is enforced by `UNIQUE(workspace_id, normalized_name)`. Projects have no owner invariant.
The schema must not materialize implicit Workspace-wide participation or require a minimum
ProjectMember count.

## Consequences

- A single-team deployment remains simple: when a User has one accessible Workspace, the UI may
  de-emphasize the selector while retaining the same explicit backend boundary.
- Item stewardship, file access, Tag governance, Discussions, Annotations and Agent context have
  one auditable root instead of inheriting accidental Project or creator semantics.
- Project membership records selected working contexts only. Workspace-wide participation remains
  implicit, open participation is self-service, and managed participation is private-like and
  explicitly curated. Managed membership exposes Project-scoped content but does not create
  canonical Item grants or Workspace authority.
- Project creators are recorded only as provenance. Workspace governance—not Project ownership—
  maintains managed participation and Project lifecycle.
- The Access Module and its immutable Casbin bundle become the sole Workspace/System
  authorization policy evaluator; Web, MCP, jobs and business Modules must call the same
  resource-action interface rather than branch on role strings.
- Database lineage constraints, explicit Workspace context and finalizer re-authorization add
  schema and API surface, but prevent accidental cross-team references.
- Instance administrators can freeze/unfreeze governance without receiving silent research-data
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
