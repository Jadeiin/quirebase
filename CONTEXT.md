# Quirebase Research Library

Quirebase stores, organizes, reads and annotates scholarly records and their
files. The same vocabulary is used by Web routes, background jobs, tests and
business Modules.

## Language

**Item**:
A bibliographic record representing a paper, book, preprint, manuscript or
other research output.
_Avoid_: Paper, Work, Document when referring to the stored bibliographic record

**Item Owner**:
The User with inherent authority to edit and permanently delete an Item, independently of
Project membership. Ownership is assigned when the Item is created and is not currently
transferable.
_Avoid_: Creator when discussing authorization

**Contributor**:
A person or organization credited in an Item's bibliographic metadata, with a role such
as author or editor. Quirebase's persistent identity is deliberately two-part: first name
and last name; a missing first name represents a single-field/literal name such as an
organization.
_Avoid_: Creator, User

**Project**:
A collaborative collection that grants members access to assigned Items.
_Avoid_: Folder, Group

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
A user-authored highlight, underline or note anchored to a File Revision and scoped either
privately or to a Project.
_Avoid_: Comment

**Discussion Message**:
A conversational message attached to an Item and visible through Item access.
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
Lookup or uploaded PDFs awaiting confirmation into the Library. A PDF Candidate Record retains
its staged file until confirmation creates the Item and associated File Revision, or until the
Import Batch is discarded. Content-addressed staged files shared by multiple pending Import
Batches remain stored until the final referencing batch is confirmed or discarded.
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
A collection-scoped authorization tier (`owner`, `editor`, or `viewer`) governing member access and editing rights within a Project.
_Avoid_: Group Role, Project Permission

**Invitation**:
A single-use, time-limited token granting registration for a new User with a designated System Role.
_Avoid_: Invite Code, Signup Token

**Login Session**:
A revocable authenticated device session belonging to one User.

**API Token**:
A revocable, time-limited programmatic credential belonging to one User and carrying that User's
current authority.
_Avoid_: Login Session, OAuth Access Token, API Key

**Job**:
A durable background task classified by a Job Kind. A Job moves from pending to running and
then to succeeded or failed; a failed attempt may return to pending while retries remain.

**Job Kind**:
A name classifying the work performed by a Job. Job Kinds are extensible and are not a closed
enumeration.

**Audit Event**:
An immutable record of a security-sensitive or data-changing action.

## Relationships

- A User is the Item Owner of zero or more Items, owns zero or more Login Sessions and API Tokens,
  and has one System Role.
- An Item has zero or more Contributors in an ordered bibliographic role. A Contributor may have a split first/last name or a single-field literal name.
- An Invitation provisions one new User with an assigned System Role.
- An Item has zero or more File Revisions, Attachments, Tags, and Discussion Messages, and at most
  one Attachment designated as its current Graphical Abstract.
- Deleting a File Revision deletes its PDF Thumbnail. Item Thumbnail resolution then falls back to
  the next eligible File Revision unless a Graphical Abstract is designated.
- An Item has at most one current Item Tag Recommendation generation.
- An Item may belong to multiple Projects.
- A Project has members with an assigned Project Role (owner, editor, or viewer).
- An Annotation belongs to exactly one File Revision.
- A Project-scoped Annotation references exactly one Project containing the Item.
- Discovery produces Candidate Records; selecting one refetches metadata into Import.
- An Import Batch holds parsed Candidate Records until confirmed into Items.
- Citation Styles format Items during export or citation generation.
- An Item may have zero or more Upstream Identifiers; DOI is represented by the
  Item's canonical DOI field and is not duplicated as an Upstream Identifier.
- A Job has one kind and may be owned by one User.
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
