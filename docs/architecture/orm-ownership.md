# ORM mapping ownership decision

Quirebase keeps `quirebase.models` as one centralized persistence mapping. Business modules
own the concepts and expose use cases, results and domain errors. Centralization keeps SQLAlchemy
relationship and mapper-order knowledge local to persistence rather than distributing it across
capability imports.

Capability-local mappings were evaluated in the issue #9 prototype. They required a metadata
aggregator while relationships such as Item–File Revision, Annotation–Project and User references
still crossed owners. The centralized layout preserves those relationships with fewer mapping
imports; conceptual ownership remains enforced separately.

## Concept owners

Every mapped class still has exactly one owner responsible for its lifecycle and business rules.
The architecture suite keeps this list complete when mappings are added or removed.

| Owner | ORM classes |
| --- | --- |
| Accounts | `User`, `LoginSession`, `LoginThrottle`, `Invitation`, `ApiToken` |
| Workspaces | `Workspace`, `WorkspaceMember`, `WorkspaceInvitation` |
| Library | `Item`, `ItemRead`, `Tag`, `ItemTag`, `ItemTagRecommendation`, `DiscussionMessage`, `ImportBatch`, `CitationStyle` |
| Projects | `Project`, `ProjectParticipant`, `ProjectItem` |
| Documents | `FileRevision`, `Attachment`, `PdfAnnotation`, `PdfAnnotationReply`, `ExportArtifact` |
| Audit | `AuditEvent` |
| Operations | `SystemSetting`, `MaintenanceSnapshot` |

## Migration interface

Alembic imports `quirebase.models` directly and reads `Base.metadata`. A clean-process test proves
that the complete metadata loads and upgrades through `head` without importing Web or business
package facades. Cross-capability ORM relationships remain persistence implementation details;
they are not re-exported as business interfaces.

## Business interfaces

[Module policy](modules.md#business-interfaces) defines facade exports and transaction ownership.
Persistence operations reuse the centralized mapping and caller's AsyncSession; the business
interface remains the use case.
