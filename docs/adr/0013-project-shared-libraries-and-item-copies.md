# ADR 0013: Projects are shared libraries with live and independent Item copies

Status: accepted.

## Context

Quirebase previously treated a Project–Item association as collection membership, an access grant
and the source of global Item edit authority. That made read access transferable: a member who could
read an Item through one Project could attach it to another Project, and revoking the original
membership did not revoke the derived access. The same association also let an Editor in any Project
change or delete the one Item and its Documents for every other Project, without making that live
sharing effect explicit.

Quirebase needs one shared collaboration scope without introducing an Instance → Workspace →
Project hierarchy. [Paperpile's Shared Library model](https://beta.paperpile.com/h/sharing-modes/)
provides the intended product precedent: a shared container owns membership and collaborative
content, while references may be live links to a personal library or independent copies. Quirebase
adopts that shape without adding Folder or Subproject entities in this decision.

## Decision

### Content scopes and Project governance

Quirebase has two first-class content scopes: a User's Personal Library and a Project. A Project is
the only shared membership and collaboration scope. Any future organizational collections inside a
Project inherit the Project's access rules rather than defining another membership hierarchy.

Project membership has three roles:

- `admin` can manage Project settings, members and roles and can perform every Editor action;
- `editor` can add, edit, organize and remove Project content; and
- `viewer` can read, download and export Project content but cannot change it. A Viewer may still
  create Private Annotations because those do not change Project content.

`Project.created_by` records provenance only. A Project has no singular owner. Every non-deleted
Project must retain at least one active Admin, so the last active Admin cannot leave, be removed, be
downgraded or be deactivated.

An archived Project is read-only with respect to Project operations: it rejects membership,
assignment, ownership, Project metadata, Project Item, Project Annotation and Discussion mutations
until restored. Live-linked Item metadata and Documents may continue to reflect changes made from
their source Personal Libraries. A User may also create or edit Private Annotations because those
do not change the archived Project.

### Project sharing modes

Every Project has a sharing mode, `live` or `independent`.

In live mode, adding an Item from the actor's Personal Library creates a Live Copy linked to that
User. The same Item content may be linked to the owner's Personal Library and multiple Projects.
Edits by an Editor in any linked Project to bibliographic metadata, File Revisions or Attachments
are visible in every linked location, including the owner's Personal Library. The interface must
show the owner and affected locations before a mutation whose effects cross Project scopes.

In independent mode, adding an Item creates a distinct Item for that Project. It may have the same
DOI or other bibliographic identity as another Item, but its metadata and Documents evolve
independently and it has no individual Item Owner. Direct import, upload, lookup or creation inside
a Project also creates an Independent Copy, including when the Project's default mode is live.

Changing a Project from live to independent forks each Live Copy for that Project and leaves other
Personal Library and Project locations linked as before. Changing a Project from independent to live
changes the default for future additions but does not silently relink existing Independent Copies.

An Admin or Editor may take ownership of an Independent Copy, which adds it to that User's Personal
Library and makes that Project Item a Live Copy. Giving up or removing ownership forks the affected
Project Item into an Independent Copy; it does not unlink the owner's other Projects. Adding another
User's Live Copy to one's Personal Library likewise creates a separate Independent Copy.

### Sharing and ownership lifecycle

Only the Item Owner may extend the same Live Copy into another Project. Read access, Project
membership and Project editing authority do not imply authority to extend somebody else's live
link. When a non-owner carries another User's Live Copy from one Project into another, Quirebase
creates an Independent Copy for the destination Project.

When an Item Owner removes the linked Item from their Personal Library, every Project that used the
Live Copy receives its own Independent Copy. The Projects no longer share Item metadata or Documents
with one another. The Personal Item is then permanently deleted; recreating or reimporting it does
not restore the former live links. Deactivating the Item Owner applies the same fork before the
account ceases to be an active synchronization source. This model permits ownerless Project Items by
design; it does not make provenance in `Item.created_by` permanent authority. Nullable
`Item.owner_id` records the current Personal Library source.

An Item Owner must remain a Project Admin or Editor for that Project to retain the owner's Live
Copies. Removing the owner from the Project, the owner leaving, or downgrading the owner to Viewer
first forks every Live Copy owned by that User in that Project into an Independent Copy. Other
Projects remain linked. This prevents a former member from changing Project content through their
Personal Library and prevents a Viewer from bypassing read-only access through live synchronization.

Metadata and Document changes, including adding or removing files, synchronize across all locations
of a Live Copy. Removing a File Revision or Attachment is permanent for that Item and must disclose
every affected live location and Annotation loss before confirmation. The immutable uploaded object
becomes eligible for physical cleanup only after no Item references it.

### Fork materialization and file reuse

A transition to an Independent Copy creates a new Item from a captured source version. It copies the
Item's bibliographic fields, Contributors, identifiers and lightweight associations to File
Revisions and Attachments. The Project Item switches to the new Item only after that copy is
complete, so it never exposes a partially forked Item and immediately stops observing later source
changes after the switch.

File Revisions and Attachments are immutable upload records that may be referenced by multiple Items
created from the same fork. Their object-store bytes, extracted PDF text and thumbnails are not
copied. A replacement or new upload receives its own object identity, and physical cleanup waits
until no Item references the old upload. Private or Project-scoped Tags, Annotations and Discussions
are never copied with Item content.

Changing a large Project's sharing mode may run as a durable workflow and process Project Items in
bounded work. Each Project Item fork validates and captures its source Item version before atomically
switching `item_id`; a concurrent source edit causes that fork step to retry instead of producing a
mixed copy.

### Project Item collaboration lifecycle

A Project Item is the lifecycle root for that Project's Tags, Annotations and Discussion Messages.
These records belong to the Project context even when the Item is a Live Copy; they do not propagate
to the owner's Personal Library or another Project.

Removing a Project Item permanently deletes that Project context together with its Project Tags,
Project Annotations, Replies and Discussion Messages. Quirebase provides no Personal or Project
Trash and no restore operation. For a Live Copy, other linked locations and the underlying Item
content remain intact. For an Independent Copy used only by that Project, removal also makes the
copied Item and its unreferenced Documents eligible for physical cleanup.

Tags belong to exactly one Personal Library or one Project. A Tag assignment belongs to the same
content scope as its Tag and Item, so a Project Tag cannot leak into another Project or a Personal
Library.

Private Annotations belong to their author and do not propagate between content scopes. Project
Annotations and their Replies belong to one Project Item. Authors alone may rewrite their content,
geometry or other authored state. Authors, Project Admins and system administrators may permanently
delete content according to their authority, but administrators cannot rewrite another author's work
or move it to a different Project.

Discussion Messages belong to one Project Item. Quirebase has no Item-global discussion shared by
all readers through unrelated Projects.

An Admin may delete a Project. Deletion removes its Project Items and Project collaboration content.
Personal Library Items and Live Copies in other Projects remain intact; Independent Copies owned
only by the deleted Project become eligible for cleanup.

## Consequences

- A Project is a real shared library rather than a folder over a global permission system.
- Live editing deliberately has effects outside the Project in which an edit was made. The product
  exposes those effects instead of implying Project-local mutation.
- Project roles control Project content, while the Item Owner alone controls extension of the same
  live link to another Project. A non-owner can still copy the research record without laundering
  access to the original Live Copy.
- A Project Item requires durable identity because Project Tags, Annotations and Discussions depend
  on that collaboration context even though removal is permanent.
- Copy and mode transitions clone bibliographic rows and lightweight file associations while reusing
  immutable uploaded objects. They never copy another scope's private or collaborative Annotations,
  Discussion Messages or Tag assignments.
- Quirebase has no Personal, Project or file Trash. Removal is permanent at the domain level even
  when physical object cleanup happens later.
- Independent Copies intentionally permit duplicate DOI and other identifiers across content
  scopes; bibliographic similarity is not authorization identity.
- This is an alpha, forward-only model change. Earlier Project roles, Item ownership assumptions and
  persisted Project–Item associations do not receive compatibility behavior unless a release plan
  explicitly requires it.

## Rejected alternatives

- A Workspace above Project was rejected because Project itself is the shared library and ACL root;
  another shared-membership layer would duplicate authority.
- A Project hierarchy with per-Folder or per-Subproject permissions was rejected because nested ACLs
  recreate the same ambiguity below Project. No Folder entity is part of this decision.
- Live-only sharing was rejected because loss of a Personal Library owner already requires a stable
  Project copy, and controlled or cross-team Projects need isolation.
- Independent-only sharing was rejected because small research teams benefit from one current
  bibliographic record and synchronized Documents across Personal Libraries and Projects.
- Allowing any reader or Editor to extend another User's Live Copy was rejected because revoking the
  source Project would not revoke the derived access.
- Item-global Tags, Annotations and Discussions were rejected because Users in unrelated Projects
  must not share collaboration context merely because their Projects refer to the same Live Copy.
- Recoverable Personal, Project and file Trash was rejected for the alpha model because it adds
  parallel visibility, authorization, restoration and retention states to every content lifecycle.
  Removal is permanent and must instead use impact previews, confirmation and Audit Events.
