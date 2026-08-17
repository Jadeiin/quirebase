# ORM mapping ownership decision

Issue #9 compared two layouts after the business Module seams in #5–#8 stabilized:

1. capability-local mapping files imported by an Alembic metadata aggregator;
2. one centralized persistence mapping with conceptual ownership enforced separately.

The executable prototype is preserved on branch `prototype/issue-9-orm-layouts`. Both layouts
configured representative cross-capability relationships, created the same scratch SQLite
tables and avoided importing Web. The capability-local layout required seven mapping imports
through an aggregator versus two for the centralized layout, while relationships such as
Item–File Revision, Annotation–Project and the many User foreign keys still crossed owners.

Quirebase therefore keeps `quirebase.models` as one centralized persistence mapping. This is not
a business Module interface: business callers continue to use operations, commands, results and
domain errors. Centralization keeps SQLAlchemy relationship and mapper-order knowledge local to
persistence instead of manufacturing imports between business packages. File length is not a
reason to reverse this decision.

## Concept owners

Every mapped class still has exactly one owner responsible for its lifecycle and business rules.
The architecture suite keeps this list complete when mappings are added or removed.

| Owner | ORM classes |
| --- | --- |
| Accounts | `User`, `LoginSession`, `LoginThrottle`, `Invitation` |
| Library | `Item`, `Author`, `ItemAuthor`, `ItemIdentifier`, `ItemRead`, `Tag`, `ItemTag`, `DiscussionMessage` |
| Projects | `Project`, `ProjectMember`, `ProjectItem` |
| Documents | `FileRevision`, `Attachment`, `PdfAnnotation`, `PdfAnnotationSegment` |
| Pipeline | `Job` |
| Discovery | `ImportBatch`, `CitationStyle` |
| Audit | `AuditEvent` |
| Operations | `SystemSetting` |

## Migration interface

Alembic imports `quirebase.models` directly and reads `Base.metadata`. A clean-process test proves
that the complete metadata loads and upgrades through `head` without importing Web or business
package facades. Cross-capability ORM relationships remain persistence implementation details;
they are not re-exported as business interfaces.

## Package facades

Package `__init__.py` files expose caller-facing use cases, results and domain errors. They do not
export concrete adapters, mutable registries, mapper collaborators, migration helpers or
compatibility-only aliases. Internal code imports those symbols from their owning implementation
module. Because Quirebase has no published Python plugin ABI, removed facade exports receive no
long-lived re-export shims.
