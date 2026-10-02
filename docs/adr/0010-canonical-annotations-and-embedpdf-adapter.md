# ADR 0010: canonical annotations with EmbedPDF as a Web adapter

Status: accepted.

Quirebase stores one canonical, strictly validated Annotation per File Revision page in the
database, which remains the only writable source of truth. Coordinates use crop-box-local,
unrotated PDF user space with a bottom-left origin. The source File Revision is immutable:
EmbedPDF runs only as a Web adapter with annotation auto-commit disabled, while exports always
derive a new Annotation Export Artifact from the source PDF and canonical records. Source-PDF
annotations remain visible but read-only and are not imported into the database.

This boundary deliberately rejects persistence or exposure of EmbedPDF vendor objects. The Web
adapter maps them to the same canonical schema used by REST and MCP, and maps canonical records
back with explicit provenance. This costs two explicit transformations, but prevents a viewer
upgrade from becoming a stored-data or public-interface migration and keeps server-side export
independent of the browser runtime. The alpha cutover migrates existing records once and provides
no dual writes, legacy wire shape or runtime compatibility reader.

Collaborative Annotation Replies are stored as separate canonical records beneath a root
Annotation. Replies inherit the root's visibility, carry their own author, body, version and
timestamps, and deliberately have no PDF geometry or vendor payload. The Web adapter translates
them to EmbedPDF reply objects only while rendering the comment sidebar.

The reader may overlay the author's private Annotations and multiple readable Projects at once.
Displayed sources are independent of the single destination selected for newly authored
Annotations. Updates and Replies retain the existing root's source. This does not duplicate an
Annotation across Projects or introduce shared ownership. Item Annotation lists display source
names, filter by source and revision, and preserve Project context when opening the reader.

REST uses one paginated `GET /workspaces/{workspace_id}/items/{item_id}/annotations` collection
for both the reader and the Item page. `revision_id` restricts the File Revision; `scope` selects
private or Project Annotations; repeated `project_id` parameters select multiple readable,
linked Projects. With no source filters it returns all scopes visible to the caller. `page` and
`per_page` apply after authorization and filtering. The response also includes readable Project
and File Revision choices and source names. The Item page uses the default page mode ordered by
latest update. The reader uses `pagination=cursor`, following `next_cursor` as `cursor` in immutable
ID order. Content updates cannot reorder that traversal, and deleting a cursor record does not
prevent loading the next page. Each request evaluates current visibility; this is not a stored
snapshot of authorization or content.

After a complete source refresh, the reader invalidates cached records absent from that source.
Records from hidden sources remain available to session history, and replayed objects stay hidden
when their source is unselected. Display, creation and export source selections are reconciled
against the current viewer Project choices on initial load and configuration refresh.

EmbedPDF's public creation controls and per-object read-only flags project backend permissions.
Its built-in comment sidebar exposes only a document-wide mutation gate; Quirebase does not patch
the vendor component to implement resource authorization. Every mutation is authorized by the
backend. Session-local Undo of an ordinary deletion uses Quirebase's versioned restore endpoints;
moderation remains a Quirebase operation on the Item page. A moderation deletion cannot be
restored through the author's ordinary restore endpoint. Hiding or archiving a Project Annotation
can be undone by moderation restore; unlocking remains a separate operation.
