from __future__ import annotations

from quirebase.library.administration import (
    admin_delete_item,
    get_storage_metrics,
    list_global_items,
)
from quirebase.library.audit import query_audit_events, record_audit_event
from quirebase.library.authors import (
    find_or_create_author,
    get_item_authors,
    parse_author_list_string,
    parse_author_name,
    search_authors_typeahead,
    set_item_authors,
)
from quirebase.library.catalog import find_duplicates, get_dashboard_data, search_library
from quirebase.library.discussions import add_discussion_message, delete_discussion_message
from quirebase.library.identifiers import (
    generate_bibtex_key,
    get_item_identifiers,
    rescan_pdf_doi,
    set_item_identifiers,
    sync_metadata_from_upstream,
)
from quirebase.library.items import (
    ItemMetadataUpdate,
    bulk_action,
    bulk_download_pdfs,
    create_item,
    get_item_workspace_data,
    mark_item_read,
    update_item,
)
from quirebase.library.tags import (
    TagConflict,
    add_tag_to_item,
    batch_add_tags_to_item,
    delete_tag,
    get_tag_matrix_for_item,
    list_accessible_tags_with_counts,
    merge_tags,
    recommend_tags_for_item,
    remove_tag_from_item,
    rename_tag,
    set_item_tags,
)

__all__ = [
    "ItemMetadataUpdate",
    "TagConflict",
    "add_discussion_message",
    "add_tag_to_item",
    "admin_delete_item",
    "batch_add_tags_to_item",
    "bulk_action",
    "bulk_download_pdfs",
    "create_item",
    "delete_discussion_message",
    "delete_tag",
    "find_duplicates",
    "find_or_create_author",
    "generate_bibtex_key",
    "get_dashboard_data",
    "get_item_authors",
    "get_item_identifiers",
    "get_item_workspace_data",
    "get_storage_metrics",
    "get_tag_matrix_for_item",
    "list_accessible_tags_with_counts",
    "list_global_items",
    "mark_item_read",
    "merge_tags",
    "parse_author_list_string",
    "parse_author_name",
    "query_audit_events",
    "recommend_tags_for_item",
    "record_audit_event",
    "remove_tag_from_item",
    "rename_tag",
    "rescan_pdf_doi",
    "search_authors_typeahead",
    "search_library",
    "set_item_authors",
    "set_item_identifiers",
    "set_item_tags",
    "sync_metadata_from_upstream",
    "update_item",
]
