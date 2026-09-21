# Quirebase Research Library

Quirebase stores, organizes, reads and annotates scholarly records and their
files. The same vocabulary is used by Web routes, background jobs, tests and
business Modules.

## Language

**Item**:
A bibliographic record representing a paper, book, preprint, manuscript or
other research output.
_Avoid_: Paper, Work, Document when referring to the stored bibliographic record

**Personal Library**:
The private content scope belonging to one User. It contains that User's Items, Personal Tags and
Private Annotations.
_Avoid_: Workspace, Personal Project

**Item Owner**:
The User whose Personal Library is linked to a Live Copy. Independent Copies have no Item Owner,
and ownership may be taken, relinquished or ended without deleting Project content.
_Avoid_: Creator, Project Owner

**Live Copy**:
A Project's linked use of an Item from one Item Owner's Personal Library. Bibliographic metadata
and Documents are shared across every linked Personal Library and Project location.
_Avoid_: Duplicate, Independent Copy

**Independent Copy**:
An Item maintained separately in one Personal Library or Project. It has no synchronization or
ownership relationship with an Item in another content scope, even when both represent the same
research output.
_Avoid_: Live Copy, Duplicate when independence matters

**Contributor**:
A person or organization credited in an Item's bibliographic metadata, with a role such
as author or editor. Quirebase's persistent identity is deliberately two-part: first name
and last name; a missing first name represents a single-field/literal name such as an
organization.
_Avoid_: Creator, User

**Project**:
A shared library and Quirebase's sole shared membership and collaboration scope. Its Items, Tags,
Annotations and Discussion Messages inherit the Project's access rules.
_Avoid_: Workspace, Folder, Group

**Project Item**:
An Item's presence and collaboration context within one Project. Its Project Tags, Project
Annotations and Project Discussion Messages are permanently deleted when it is removed.
_Avoid_: Folder entry, bare association

**Document**:
Stored file content associated with an Item, represented by a File Revision or
Attachment.
_Avoid_: Item

**File Revision**:
An immutable primary PDF version associated with one or more Items derived from the same source.
It is pending while awaiting inspection and ready after its text and page geometry have been
successfully extracted.
_Avoid_: Attachment, Item version

**Attachment**:
A supplementary file associated with one or more Items derived from the same source that is not a
primary PDF.
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
a File Revision and scoped either privately or to a Project Item.
_Avoid_: Comment

**Annotation Reply**:
A user-authored conversational response attached to one Annotation. It inherits that Annotation's
visibility and has no independent PDF geometry or scope.
_Avoid_: Annotation, Discussion Message

**Annotation Export Artifact**:
A temporary PDF derived from a File Revision and its visible Annotations for download. It remains
available until its recorded expiration time and is then eligible for physical cleanup.

**Discussion Message**:
A conversational message attached to a Project Item and visible through that Project.
_Avoid_: Annotation, Comment

**Tag**:
A user-defined taxonomy label scoped to either one Personal Library or one Project and attached to
Items within that same content scope.
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
A global authorization tier (`administrator` or `member`) governing instance-wide administration and Item deletion.
_Avoid_: Global Role, User Role

**Project Role**:
A Project-scoped authorization tier (`admin`, `editor`, or `viewer`). Admins govern membership and
settings, Editors manage content, and Viewers have read-only Project access.
_Avoid_: Group Role, Project Permission

**Archived Project**:
A Project that permits no Project operations. Its Live Copies may still reflect changes made from
their source Personal Libraries.
_Avoid_: Deleted Project

**Invitation**:
A single-use, time-limited token granting registration for a new User with a designated System Role.
_Avoid_: Invite Code, Signup Token

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
  whose identity is being destroyed.
- **Remove** detaches an association while preserving both resources. Use remove for an
  Item–Tag, Project–Item or Project–member relationship; the relationship-owned context is deleted,
  but the Item, Tag, Project and User identities are preserved.

An HTTP DELETE method can therefore generate either a delete_* or remove_* operation ID:
the method describes the transport, while the verb describes the domain effect. discard is
reserved for abandoning staged transient work such as an Import Batch, and revoke is reserved
for invalidating a Login Session or API Token without deleting its audit/persistence record.

## Relationships

- A User is the Item Owner of zero or more Live Copies, has one Personal Library, owns zero or more
  Login Sessions and API Tokens, and has one System Role.
- An Item has zero or more Contributors in an ordered bibliographic role. A Contributor may have a split first/last name or a single-field literal name.
- An Invitation provisions one new User with an assigned System Role.
- An Item has zero or more File Revisions and Attachments, and at most
  one Attachment designated as its current Graphical Abstract.
- A File Revision and its PDF Thumbnail become eligible for physical cleanup only after no Item
  references them. Item Thumbnail resolution then falls back to the next eligible File Revision
  unless a Graphical Abstract is designated.
- An Item has at most one current Item Tag Recommendation generation.
- A Live Copy may appear in an Item Owner's Personal Library and multiple Projects; an Independent
  Copy belongs to one content scope.
- A Project has members with an assigned Project Role (admin, editor, or viewer) and at least one
  active Admin.
- A Project Item has zero or more Project Tags, Project Annotations and Project Discussion Messages.
- An Annotation belongs to exactly one File Revision.
- An Annotation has zero or more Annotation Replies.
- An Annotation Export Artifact is derived from one File Revision and expires independently of it.
- A Project Annotation references exactly one Project Item.
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
