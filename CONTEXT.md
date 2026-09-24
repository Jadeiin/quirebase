# Quirebase Research Library

Quirebase stores, organizes, reads and annotates scholarly records and their
files. The same vocabulary is used by Web routes, background jobs, tests and
business Modules.

## Language

**Item**:
A bibliographic record representing a paper, book, preprint, manuscript or
other research output.
_Avoid_: Paper, Work, Document when referring to the stored bibliographic record

**Item Section**:
A Web navigation and read-model section for one Item, such as Overview, Metadata, Files,
Organize, Annotations or Discussion. It is a presentation projection, not a Workspace or a
separate domain aggregate.
_Avoid_: Item Workspace

**Workspace**:
A knowledge space and the data-governance and authorization boundary for its Items,
Documents, Tags, Discussions and Projects. Every Workspace-owned resource has one Workspace
lineage. Workspaces all use the same domain and authorization rules; there is no personal/shared
Workspace kind. User provisioning creates an ordinary Workspace for its new User.
_Avoid_: Tenant when discussing research data

**Workspace Member**:
A User with an active or suspended membership in a Workspace. An active membership is required
for Workspace data access; suspension and termination remove effective access without changing
the provenance of Workspace-owned resources.

**Workspace Role**:
The only persistent resource role axis in Quirebase: `owner`, `admin`, `editor`, `reviewer` or
`viewer`. Workspace capabilities, evaluated through the Access Module, govern Workspace data and
governance operations. A role is never inferred from `created_by`.

**Workspace Capability**:
An Access Module decision granting or denying one operation for a User within a Workspace, such
as reading Items, editing metadata, managing files, governing Tags or managing members. A
capability is evaluated only after Workspace lineage and active membership are established.

**Item Stewardship**:
The Workspace-governed authority to maintain or permanently delete a canonical Item. It is
derived from Workspace capability, not from the User who created the Item. `created_by` remains
provenance only.
_Avoid_: Item Owner when discussing authorization

**Contributor**:
A person or organization credited in an Item's bibliographic metadata, with a role such
as author or editor. Quirebase's persistent identity is deliberately two-part: first name
and last name; a missing first name represents a single-field/literal name such as an
organization.
_Avoid_: Creator, User

**Project**:
A collaboration context inside one Workspace that organizes a working set of Items and contains
Project-scoped annotations, discussions and notes. A Project does not grant access to an Item or
raise a User's Workspace capability. A Project has no owner; `created_by` is provenance only.
_Avoid_: Folder, Group

**Project Member**:
An explicit User–Project association that records a User's selected Project working context. It
has no Project role and grants no Workspace capability. It controls discoverability of `managed`
Projects only; it never grants access to canonical Workspace Items. Workspace-participation
Projects have implicit participation and no Project Member rows.

**Project Visibility**:
The retained Project field that expresses discoverability and participation policy, not a Project
role or Workspace capability: `workspace` means all active Workspace members can discover and
implicitly participate, with no Project Member rows; `open` means all active Workspace members can
discover the Project and may choose to join or leave; `managed` means only Project Members and
Workspace owners/admins can discover the Project and its Project-scoped content, with participation
curated by Workspace governance. Managed visibility never changes access to canonical Workspace
Items.

**ProjectItem**:
An association placing an Item from the same Workspace in a Project working set. ProjectItem
does not grant Item access or any Workspace capability.

**Document**:
Stored file content associated with an Item, represented by a File Revision or
Attachment.
_Avoid_: Item

**File Revision**:
An immutable primary PDF version associated with an Item. It is pending while awaiting
inspection and ready after its text and page geometry have been successfully extracted.
_Avoid_: Attachment, Item version

**Attachment**:
A supplementary file associated with an Item that is not its primary PDF.
An Attachment may carry a distinguished role such as Graphical Abstract.
_Avoid_: File Revision

**Graphical Abstract**:
The single Attachment currently designated as an Item's author- or curator-supplied representative
image. Replacing the designation does not turn the previous image into a File Revision.

**PDF Thumbnail**:
A derived first-page image belonging to exactly one File Revision. It has the same lifetime as that
File Revision and is not independently curated.

**Item Thumbnail**:
The representative image resolved for display. The current Graphical Abstract is authoritative;
otherwise the newest ready File Revision with an available PDF Thumbnail is used.

**Annotation**:
A user-authored text mark, note, free text, ink stroke or geometric shape anchored to one page of
a File Revision and scoped either privately or to a Project.
_Avoid_: Comment

**Annotation Reply**:
A user-authored conversational response attached to one Annotation. It inherits that Annotation's
visibility and has no independent PDF geometry or scope.
_Avoid_: Annotation, Discussion Message

**Annotation Export Artifact**:
A temporary PDF derived from a File Revision and its visible Annotations for download. It remains
available until its recorded expiration time and is then eligible for physical cleanup.

**Discussion Message**:
A conversational message attached to an Item and visible through Workspace Item access. A
Project Discussion/Note is a separate Project-scoped collaboration resource governed by Project
visibility and Workspace capabilities.
_Avoid_: Annotation, Comment

**Tag**:
A user-defined taxonomy label attached to Items for cross-cutting categorization.
Item Keywords may be presented as suggested Tag names, but become Tags only after explicit User
selection.
_Avoid_: Category, Keyword, Folder

**Item Tag Recommendation**:
A transient, ranked set of single-word and compound-phrase candidate Tag names generated from an
Item's title, abstract and latest ready File Revision. A recommendation is never a Tag until a User
selects it.
_Avoid_: Item Keyword, Tag, automatic Tag

**Candidate Record**:
An uncommitted bibliographic metadata payload retrieved via Discovery or Identifier Lookup, subject to preview before Import.
_Avoid_: Staged Item, Provisional Work

**Import Batch**:
A staged collection of Candidate Records and diagnostics from a bibliography file, Identifier
Lookup or uploaded PDFs awaiting confirmation into the Library. A PDF Import Batch is pending
while its durable preparation workflow extracts identifiers and retrieves Candidate Records, ready
for confirmation after successful preparation, and failed after a terminal workflow error. Retrying
a failed batch preserves its staged PDFs and assigns a new durable workflow. A pending PDF Import Batch
whose associated workflow is terminal or missing converges to failed before retry. A PDF Candidate Record retains
its independently owned UUID object until confirmation creates the Item and associated File
Revision, or until the Import Batch is discarded. After successful confirmation, the batch becomes
committed, retains only the recorded committed Item IDs for idempotent confirmation responses, and no
longer retains staged PDF object references.
_Avoid_: Staged Import, Import Queue

**Import**:
Creation of candidate Item metadata from a known identifier, bibliography file
or uploaded PDF, followed by explicit confirmation.
_Avoid_: Discovery

**Discovery**:
Search of an external Provider using terms and conditions to find candidates
that may later enter Import.
_Avoid_: Import, Library Search

**Library Search**:
Search over Items and extracted local PDF text already stored in Quirebase.
_Avoid_: Discovery

**Citation Style**:
A CSL specification defining how Item bibliographic metadata is formatted into academic citations and bibliographies.
_Avoid_: Reference Template, CSL Profile

**Provider**:
A fixed external scholarly metadata source such as OpenAlex, Crossref or
PubMed.
_Avoid_: Plugin

**Upstream Identifier**:
An identifier issued by a Provider for an Item, stored as a provider/value pair
when it is not the canonical DOI. The pair is used to refetch metadata and to
show provenance; DOI remains the Item's canonical identifier rather than a
second provider-specific record.
_Avoid_: Source ID, External ID when the issuing Provider matters

**User**:
An authenticated human account with an assigned System Role.
_Avoid_: Account, Profile

**System Role**:
A global authorization tier (`administrator` or `member`) governing instance-wide administration,
tenancy/lifecycle governance and account operations. It does not grant implicit access to
Workspace-owned research data.
_Avoid_: Global Role, User Role

**Invitation**:
A single-use, time-limited instance-level mechanism for provisioning or registering a User. A
Workspace admission uses a separate WorkspaceInvitation and does not follow from instance
registration alone.
_Avoid_: Invite Code, Signup Token

**Workspace Invitation**:
A single-use, time-limited admission mechanism for adding an existing User to a Workspace.
Accepting it creates or activates a Workspace Member; it does not provision instance identity.

**Login Session**:
A revocable authenticated device session belonging to one User.

**API Token**:
A revocable, time-limited programmatic credential belonging to one User and carrying that User's
current authority.
_Avoid_: Login Session, OAuth Access Token, API Key

**Audit Event**:
An immutable record of a security-sensitive or data-changing action.

## API mutation verbs

The HTTP API and its generated operation IDs use these verbs deliberately:

- **Delete** removes a first-class resource from its owning lifecycle. Use delete for an
  Item, Project, Annotation, File Revision, Attachment, Discussion Message or other resource
  whose identity is being destroyed (including a soft-deleted resource whose normal projection
  no longer exposes it).
- **Remove** detaches an association while preserving both resources. Use remove for an
  Item–Tag, Project–Item or Project–member relationship; neither the Item, Tag, Project nor User
  is deleted.

An HTTP DELETE method can therefore generate either a delete_* or remove_* operation ID:
the method describes the transport, while the verb describes the domain effect. discard is
reserved for abandoning staged transient work such as an Import Batch, and revoke is reserved
for invalidating a Login Session or API Token without deleting its audit/persistence record.

## Relationships

- A User owns zero or more Login Sessions and API Tokens, has one System Role, and may belong to
  zero or more Workspaces through Workspace Members.
- An Item has zero or more Contributors in an ordered bibliographic role. A Contributor may have a split first/last name or a single-field literal name.
- An Invitation provisions or registers one new User with an assigned System Role; successful
  provisioning also creates an ordinary Workspace and owner membership for that User.
- A Workspace has Workspace Members, a canonical Item Library, shared Tags, Item Discussions and
  Projects. Workspace ownership and access are evaluated through Workspace capabilities.
- An Item has zero or more File Revisions, Attachments, Tags, and Discussion Messages, and at most
  one Attachment designated as its current Graphical Abstract.
- Deleting a File Revision deletes its PDF Thumbnail. Item Thumbnail resolution then falls back to
  the next eligible File Revision unless a Graphical Abstract is designated.
- An Item has at most one current Item Tag Recommendation generation.
- An Item may belong to multiple Projects in the same Workspace; ProjectItem is an organizational
  association and never grants Item access.
- A Project has Project Members only when its visibility is `open` or `managed`; these
  role-less associations record participation. For `managed` Projects they also gate Project
  discoverability, but never grant access to canonical Workspace Items. A `workspace` Project has
  implicit participation and no Project Member rows. A Project has no owner or ownership-transfer
  operation; `created_by` is provenance, while Project lifecycle and participation operations use
  Workspace capabilities.
- An Annotation belongs to exactly one File Revision.
- An Annotation has zero or more Annotation Replies.
- An Annotation Export Artifact is derived from one File Revision and expires independently of it.
- A Project-scoped Annotation references exactly one Project containing the Item.
- Discovery produces Candidate Records; selecting one refetches metadata into Import.
- An Import Batch holds parsed Candidate Records until confirmed into Items; a committed batch retains
  the confirmation result but is no longer an active staging reservation.
- Citation Styles format Items during export or citation generation.
- An Item may have zero or more Upstream Identifiers; DOI is represented by the
  Item's canonical DOI field and is not duplicated as an Upstream Identifier.
- An Audit Event may reference an actor and a target.

## Example dialogue

> Dev: “Does an OpenAlex keyword query Import Items immediately?”
>
> Domain expert: “No. That is Discovery. Selecting a result refetches its
> identifier into Import, and the Item is only created after confirmation.”
>
> Dev: “Is an uploaded PDF the Item?”
>
> Domain expert: “No. The Item is the bibliographic record; the PDF is a File
> Revision of that Item.”
>
> Dev: “Is a Keyword the same as a Tag?”
>
> Domain expert: “No. Keywords are author- or provider-supplied metadata on the Item;
> Tags are user-authored taxonomy labels.”

## Flagged ambiguities

- The UI may use “论文” conversationally, but Python domain code uses Item.
- Existing `/documents/...` routes refer to file delivery; Document must not be
  used as a synonym for Item.
- “Search” must be qualified as Library Search or Discovery when ambiguity is
  possible.
- “Keyword” refers to upstream author/provider metadata; “Tag” refers to user-managed taxonomy.
- “Audit Log” refers to the UI query interface; stored records are always Audit Events.
