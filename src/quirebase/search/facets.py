from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from quirebase.models import Item


def extract_search_facets(items: list[Item]) -> dict[str, Any]:
    years: set[str] = set()
    reference_types: set[str] = set()
    for item in items:
        if item.publication_date:
            year = item.publication_date[:4]
            if year.isdigit():
                years.add(year)
        if item.reference_type:
            reference_types.add(item.reference_type)
    return {
        "years": sorted(years, reverse=True),
        "reference_types": sorted(reference_types),
        "count": len(items),
    }
