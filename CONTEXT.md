# Quirebase Research Library

Quirebase stores, organizes, reads and annotates scholarly records and their
files. The same vocabulary is used by Web routes, background jobs, tests and
business Modules.

## Language

**Item**:
A bibliographic record representing a paper, book, preprint, manuscript or
other research output.
_Avoid_: Paper, Work, Document when referring to the stored bibliographic record

**Project**:
A collaborative collection that grants members access to assigned Items.
_Avoid_: Folder, Group

**Document**:
Stored file content associated with an Item, represented by a File Revision or
Attachment.
_Avoid_: Item

**File Revision**:
An immutable primary PDF version associated with an Item.
_Avoid_: Attachment, Item version

**Attachment**:
A supplementary file associated with an Item that is not its primary PDF.
_Avoid_: File Revision

**Annotation**:
A user-authored highlight or note anchored to a File Revision and scoped either
privately or to a Project.
_Avoid_: Comment

**Discussion Message**:
A conversational message attached to an Item and visible through Item access.
_Avoid_: Annotation, Comment

**Tag**:
A user-defined taxonomy label attached to Items for cross-cutting categorization.
_Avoid_: Category, Keyword, Folder

**Candidate Record**:
An uncommitted bibliographic metadata payload retrieved via Discovery or Identifier Lookup, subject to preview before Import.
_Avoid_: Staged Item, Provisional Work

**Import Batch**:
A staged collection of parsed Candidate Records and diagnostics from a bibliography file awaiting confirmation into the Library.
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

**Job**:
A durable background task with lease, retry and terminal-state semantics.

**Audit Event**:
An immutable record of a security-sensitive or data-changing action.

## Relationships

- A User owns zero or more Items and Login Sessions, and has one System Role.
- An Invitation provisions one new User with an assigned System Role.
- An Item has zero or more File Revisions, Attachments, Tags, and Discussion Messages.
- An Item may belong to multiple Projects.
- A Project has members with an assigned Project Role (owner, editor, or viewer).
- An Annotation belongs to exactly one File Revision.
- A Project-scoped Annotation references exactly one Project containing the Item.
- Discovery produces Candidate Records; selecting one refetches metadata into Import.
- An Import Batch holds parsed Candidate Records until confirmed into Items.
- Citation Styles format Items during export or citation generation.
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
