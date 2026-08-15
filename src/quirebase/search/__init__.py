from __future__ import annotations

from quirebase.search.engine import reindex_all, search_index
from quirebase.search.facets import extract_search_facets
from quirebase.search.postgres import PostgreSQLSearchIndex
from quirebase.search.protocol import SearchIndex
from quirebase.search.sqlite import SQLiteSearchIndex

__all__ = [
    "PostgreSQLSearchIndex",
    "SQLiteSearchIndex",
    "SearchIndex",
    "extract_search_facets",
    "reindex_all",
    "search_index",
]
