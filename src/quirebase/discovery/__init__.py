from __future__ import annotations

from quirebase.discovery.activity import get_user_imported_identifiers, record_search_audit
from quirebase.discovery.bibliography import (
    SUPPORTED_FORMATS,
    export_bibliography,
    parse_bibliography,
)
from quirebase.discovery.imports import (
    BatchConflict,
    UpstreamServiceError,
    commit_import_batch,
    export_accessible_bibliography,
    export_selected_bibliography,
    import_published_pdf,
    import_unpublished_pdf,
    stage_import_batch,
    stage_metadata_batch,
)
from quirebase.discovery.lookup import (
    Identifier,
    MetadataLookupError,
    MetadataNotFoundError,
    lookup_metadata,
    parse_identifier,
)
from quirebase.discovery.search import (
    SearchClause,
    SearchPage,
    SearchResult,
    search_metadata,
)

__all__ = [
    "SUPPORTED_FORMATS",
    "BatchConflict",
    "Identifier",
    "MetadataLookupError",
    "MetadataNotFoundError",
    "SearchClause",
    "SearchPage",
    "SearchResult",
    "UpstreamServiceError",
    "commit_import_batch",
    "export_accessible_bibliography",
    "export_bibliography",
    "export_selected_bibliography",
    "get_user_imported_identifiers",
    "import_published_pdf",
    "import_unpublished_pdf",
    "lookup_metadata",
    "parse_bibliography",
    "parse_identifier",
    "record_search_audit",
    "search_metadata",
    "stage_import_batch",
    "stage_metadata_batch",
]
