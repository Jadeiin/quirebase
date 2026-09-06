# ADR 0010: canonical annotations with EmbedPDF as a Web adapter

Status: accepted.

Quirebase stores one canonical, strictly validated Annotation per File Revision page in the
database, which remains the only writable source of truth. Coordinates use crop-box-local,
unrotated PDF user space with a bottom-left origin. The source File Revision is immutable:
EmbedPDF runs only as a Web adapter with annotation auto-commit disabled, while exports always
derive a new Annotation Export Artifact from the source PDF and canonical records. Source-PDF
annotations remain visible but read-only by default and are not imported into the database. PDF
Import explicitly supports three modes: `preserve` retains native annotation objects; `strip`
writes a derived PDF with page markup annotations removed; and `import` parses supported native
markup into private canonical Annotation records and writes the same derived, annotation-free PDF.
The latter two modes never mutate the immutable source object. Importing removes only page markup
objects returned by the PDF annotation API; links, widgets and marks flattened into page content
are left untouched.

This boundary deliberately rejects persistence or exposure of EmbedPDF vendor objects. The Web
adapter maps them to the same canonical schema used by REST and MCP, and maps canonical records
back with explicit provenance. This costs two explicit transformations, but prevents a viewer
upgrade from becoming a stored-data or public-interface migration and keeps server-side export
independent of the browser runtime. The alpha cutover migrates existing records once and provides
no dual writes, legacy wire shape or runtime compatibility reader.

Imported native annotations are attributed to the User performing the Import, have private scope,
and receive new Quirebase UUIDs. Unsupported native subtypes are diagnosed and skipped rather than
blocking the PDF Import.

Collaborative Annotation Replies are stored as separate canonical records beneath a root
Annotation. Replies inherit the root's visibility, carry their own author, body, version and
timestamps, and deliberately have no PDF geometry or vendor payload. The Web adapter translates
them to EmbedPDF reply objects only while rendering the comment sidebar.
