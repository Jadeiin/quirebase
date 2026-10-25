# Quirebase Research Library

Quirebase stores, organizes, reads and annotates scholarly records and their files. This glossary
defines the concepts, relationships and language used across business modules, adapters and tests.
Detailed behavior lives in [architecture contracts](docs/architecture/modules.md).

## Language

**Item**:
A bibliographic record representing a paper, book, preprint, manuscript or other research output.
_Avoid_: Paper, Work or Document for the stored record.

**Work**:
The Commonmeta bibliographic value describing an Item's research output. Its external identity
is independent of the Item's identity, Workspace and governance.

**Reference Type**:
The Work's Commonmeta classification, such as JournalArticle, Book, BookChapter, Dataset or Preprint.

**Publication Date**:
The publication year, year and month, or complete calendar date, stored as `YYYY`, `YYYY-MM` or
`YYYY-MM-DD`, or a full ISO date-time supplied by the Work. Missing month or day values do not
imply January or the first day of a month.
Date ranges retain only a shared year or month; a range spanning years has no single Publication Date.

**Citation Key**:
A User-editable key used to name an Item in citation and bibliography output.
_Avoid_: BibTeX Key when discussing the format-independent Item property.

**Item Section**:
A navigation and read-model section for one Item: Overview, Metadata, Files, Organize, Annotations
or Discussion. It is a presentation projection, not a separate domain aggregate.
_Avoid_: Item Workspace.

**Workspace**:
A knowledge space and the data-governance and authorization boundary for its Items, Documents,
Tags, Discussions and Projects. Every owned resource has one Workspace lineage. All Workspaces
use the same domain and authorization rules; there is no personal/shared Workspace kind.
User provisioning creates an ordinary Workspace for its new User.
_Avoid_: Tenant when discussing research data.

**Workspace Freeze**:
An instance-administrator read-only overlay that blocks Workspace mutations while retaining
active members' content reads, downloads and exports. Unfreezing preserves the underlying active
or archived state. It neither suspends members nor grants the administrator content access.

**Workspace Member**:
A User with an active or suspended membership in a Workspace. Effective data access requires
both an active User and active membership. Suspension and termination remove effective access
while preserving Workspace content and authorship. An active non-owner member may leave an
active, unfrozen Workspace. Leaving terminates that membership generation and its Project
participation. Rejoining requires a new invitation and creates a new membership generation.

**Workspace Owner**:
The User assigned to a Workspace's unique current active owner membership. The assignment
survives User deactivation, while effective access requires an active User.
An instance administrator may explicitly reassign ownership with a recorded reason, granting the
selected active User owner access and retaining the previous owner as a Workspace admin.

**Workspace Role**:
The persistent resource role within a Workspace: owner, admin, editor, reviewer or viewer.
The Access Module evaluates its resource-action grants; authorship is separate provenance.

**Authorization Decision**:
An Access Module allow/deny result over a subject, resource, action, lifecycle and relation.
Workspace lineage and active membership are established before the decision. For example, an
editor may update an Item in an active Workspace, while an admin may delete another author's
Item Discussion.
A dotted key such as `item.update` represents the resource/action pair in API and Audit values.

**Item Stewardship**:
Workspace-governed authority to maintain or permanently delete a canonical Item, derived from
a Workspace resource-action decision. The User who created the Item is recorded as provenance.
_Avoid_: Item Owner when discussing authorization.

**Contributor**:
A person or organization credited in one Work, with roles such as Author or Editor. Credits
are ordered and record-local; matching names do not establish a shared researcher identity.
_Avoid_: Creator, User.

**Affiliation**:
An institution credited with a Contributor on a particular Work, optionally with an identifier.
It belongs to that record's credit rather than to an independent Contributor identity.

**Project**:
A collaboration context within one Workspace that organizes Items and contains Project-scoped
Annotations and Discussions. Workspace policy governs authority; a Project has no owner and grants no
canonical Item access.
Archiving preserves the Project for restoration. Deleting removes its root and Project-owned
context while preserving canonical Workspace Items and historical Audit Events.
_Avoid_: Folder, Group.

**Project Participant**:
A User participating in a Project working context, implicitly in workspace mode or through an
explicit selection in open/managed modes. Explicit selections belong to one Workspace membership
generation. Suspension retains selections without effective participation; termination removes them.

**Project Participation**:
The Project's discoverability and participation mode:

- **workspace**: all active Workspace members discover and implicitly participate.
- **open**: all active Workspace members discover the Project and may join or leave.
- **managed**: participants and Workspace governors discover the Project; governance curates participation.

Participation grants no additional Workspace authority or canonical Item access.

**ProjectItem**:
An association placing an Item from the same Workspace into a Project working set. Project
Annotations and their Replies bind to this association and are permanently deleted with it.
The canonical Item, its files, private Annotations and other Project associations remain.

**Document**:
Stored file content associated with an Item, represented by a File Revision or Attachment.
_Avoid_: Item.

**File Revision**:
An immutable primary PDF version associated with an Item. It is pending during inspection,
ready after successful text/geometry extraction, or failed while retaining its source for retry.
_Avoid_: Attachment, Item version.

**Attachment**:
A supplementary Item file, optionally carrying a distinguished role such as Graphical Abstract.
_Avoid_: File Revision.

**Graphical Abstract**:
The single Attachment designated as an Item's author- or curator-supplied representative image.

**PDF Thumbnail**:
A derived first-page image belonging to exactly one File Revision and sharing its lifetime.

**Item Thumbnail**:
The representative image resolved for display: the current Graphical Abstract, or otherwise the
newest ready File Revision with an available PDF Thumbnail.

**Annotation**:
A user-authored text mark, note, free text, ink stroke or geometric shape anchored to one page
of a File Revision. Its private or Project audience is fixed at creation.
_Avoid_: Comment.

**Annotation Reply**:
A conversational response attached to an Annotation, inheriting its visibility without independent
PDF geometry or scope.
_Avoid_: Annotation, Discussion Message.

**Annotation Export Artifact**:
A temporary PDF derived from a File Revision and its visible Annotations for authorized download.
It has its own expiration and lifetime.

**Discussion Message**:
A conversational message attached to an Item or Project. Item Discussions follow Workspace Item
access; Project Discussions follow Project discoverability and Workspace policy.
_Avoid_: Annotation, Comment.

**Tag**:
A Workspace taxonomy label attached to Items for cross-cutting categorization. Work keywords
become Tags only after explicit User selection.
_Avoid_: Category, Keyword, Folder.

**Item Tag Recommendation**:
A transient ranked set of candidate Tag names generated from an Item's title, abstract and latest
ready File Revision. It becomes a Tag assignment only when selected.
_Avoid_: Item Keyword, Tag, automatic Tag.

**Candidate Record**:
Uncommitted Work metadata prepared for review before Import, retrieved through Discovery or
Identifier Lookup, parsed from a bibliography, or initialized from a PDF. Retrieved candidates
carry Provider and lookup-input context. A basic PDF candidate has minimal metadata and requires
explicit selection to create an Item with its PDF.
_Avoid_: Staged Item, Provisional Work.

**Import Batch**:
A collection tracking Import sources, Candidate Records, diagnostics and the confirmation result.
An uncommitted batch is pending, ready or failed. Pending means preparation has not finished,
including queued and running preparation; ready means preparation finished with at least one
Candidate Record for review; failed means preparation failed or finished without candidates.
Ready batches may include diagnostics and basic PDF candidates requiring explicit selection.
Preparing candidates creates no Items. Confirmation creates Items and sets the batch to committed,
retaining the created Item identities for confirmation replay. Deleting a committed batch preserves
imported Items and Documents but ends replay and batch-scoped Library reads. Document processing
and recommendations may continue after confirmation.
_Avoid_: Staged Import, Import Queue.

**Import**:
Adding reference metadata from an identifier, bibliography file or PDF through explicit confirmation.
_Avoid_: Discovery.

**Discovery**:
Searching an external Provider by terms and conditions to find candidates for Import.
_Avoid_: Import, Library Search.

**Library Search**:
Search over Items and extracted local PDF text stored in Quirebase.
_Avoid_: Discovery.

**Citation Style**:
A CSL specification for formatting bibliographic metadata into academic citations and bibliographies.
_Avoid_: Reference Template, CSL Profile.

**Provider**:
A fixed external scholarly metadata source such as OpenAlex, Crossref or PubMed.
_Avoid_: Plugin.

**Identifier Namespace**:
A scholarly identifier kind, such as DOI, PMID, PMCID, arXiv ID or OpenAlex Work ID. A namespace is
distinct from a Provider: Crossref and DataCite both return DOIs. ISSN identifies a journal.

**Upstream Identifier**:
A bibliographic identifier declared by Work.id or Work.identifiers. A Work may carry multiple
values of one kind, and separate Items may share them. Lookup input is query context rather than
a confirmed identity. Container, contributor and related-resource identifiers describe those entities.
_Avoid_: Identifier claim, Workspace-unique bibliographic identity.

**User**:
A human account with a System Role. Deactivation removes authentication and effective authority
while preserving ownership assignments, memberships and provenance.
_Avoid_: Account, Profile when naming the domain entity.

**System Role**:
An instance authorization tier, administrator or member, governing account operations and instance
governance. It grants no implicit access to Workspace research data.
_Avoid_: Global Role, User Role.

**Invitation**:
A single-use, time-limited instance admission mechanism for provisioning a User. Workspace
admission is separate. Revocation invalidates the link; reissue replaces it with a new Invitation.
_Avoid_: Invite Code, Signup Token.

**Workspace Invitation**:
A single-use, time-limited mechanism for admitting an existing User to a Workspace. Acceptance
creates a new membership generation; it does not reactivate suspended memberships or restore
previous Project selections.

**Login Session**:
A revocable authenticated device session belonging to one User.

**API Token**:
A revocable, time-limited programmatic credential carrying its User's current authority.
_Avoid_: Login Session, OAuth Access Token, API Key.

**Audit Event**:
An immutable, retention-bound record of a security-sensitive or data-changing action.

## API mutation verbs

The HTTP API and its generated operation IDs use these verbs deliberately:

- **Delete** removes a first-class resource from its owning lifecycle. Use delete for an
  Item, Project, Annotation, File Revision, Attachment, Discussion Message or other resource
  whose identity is being destroyed (including a soft-deleted resource whose normal projection
  no longer exposes it).
- **Remove** detaches an association while preserving both resources. Use remove for an
  Item–Tag, Project–Item or Project–participant relationship; neither the Item, Tag, Project nor User
  is deleted.

An HTTP DELETE method can therefore generate either a `delete_*` or `remove_*` operation ID:
the method describes the transport, while the verb describes the domain effect. **Discard** is
reserved for abandoning staged transient work such as an unconfirmed Import Batch, and **Revoke**
is reserved for invalidating an Invitation, Workspace Invitation, Login Session or API Token while
preserving its record.

## Relationships

- A User owns zero or more Login Sessions and API Tokens, has one System Role, and may belong to
  zero or more Workspaces through Workspace Members.
- An Item stores one Work with zero or more Contributors in ordered bibliographic roles. A
  Contributor may have split given/family names or a single-field literal name, and zero or more
  record-local Affiliations.
- An Invitation provisions or registers one new User with an assigned System Role; successful
  provisioning also creates an ordinary Workspace and owner membership for that User.
- A Workspace has Workspace Members, a canonical Item Library, shared Tags, Item Discussions and
  Projects. Workspace ownership and access are evaluated through resource-action decisions.
- An Item has zero or more File Revisions, Attachments, Tags, and Discussion Messages, and at most
  one Attachment designated as its current Graphical Abstract.
- Deleting a File Revision deletes its PDF Thumbnail. Item Thumbnail resolution then falls back to
  the next eligible File Revision unless a Graphical Abstract is designated.
- An Item has at most one current Item Tag Recommendation generation.
- An Item may belong to multiple Projects in the same Workspace; ProjectItem is an organizational
  association and never grants Item access.
- A Project records explicit Project Participant selections in `open` or `managed` mode;
  these role-less associations record participation. For `managed` Projects they also gate Project
  discoverability, but never grant access to canonical Workspace Items. A `workspace` Project has
  implicit participation and no explicit Project Participant selections. A Project has no owner or
  ownership-transfer operation; `created_by` is provenance, while Project lifecycle and participation
  operations use Workspace resource-action decisions.
- An Annotation belongs to exactly one File Revision.
- An Annotation has zero or more Annotation Replies, which inherit its audience.
- An Annotation Export Artifact is derived from one File Revision and expires independently of it.
- A Project-scoped Annotation references exactly one ProjectItem for its File Revision's Item.
  Removing that association permanently deletes its Project Annotations and their Replies.
- Discovery produces Candidate Records; selecting one refetches metadata into Import.
- An Import Batch holds Candidate Records and staged source files until confirmed into Items,
  deleted or expired. A committed batch retains the confirmation result and releases its staging
  data; deleting the committed batch preserves the imported Items and Documents.
- Citation Styles format Items during export or citation generation.
- An Item may have zero or more supported Upstream Identifiers, including multiple DOIs.
  Shared identifiers yield Library duplicate suggestions, independently of Item UUID identity.
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
> Domain expert: “No. Keywords are author- or provider-supplied metadata on the Work;
> Tags are user-managed taxonomy labels in the Workspace.”

## Flagged ambiguities

- The UI may use “论文” conversationally, but Python domain code uses Item.
- “Document” refers to stored file content; “Item” refers to the bibliographic record.
- “Search” must be qualified as Library Search or Discovery when ambiguity is
  possible.
- “Keyword” refers to upstream author/provider metadata; “Tag” refers to user-managed taxonomy.
- “Audit Log” refers to the UI query interface; stored records are always Audit Events.
