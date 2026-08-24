from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

from inquiro.identifiers import parse_doi
from inquiro.models import CandidateNotFound, ProviderRecord, ProviderUnavailable
from inquiro.parsing import (
    _clean_markup,
    _collect_urls,
    _first,
    normalize_reference_type,
)
from inquiro.providers._contracts import ProviderContext, ProviderDefinition


class DataCiteLookupAdapter:
    def lookup(
        self, client: ProviderContext, value: str, settings: Any, *, endpoint: str
    ) -> ProviderRecord:
        try:
            body = client._get(f"{endpoint}/{quote(value, safe='')}")
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("DataCite returned invalid metadata") from error
        attributes = (payload.get("data") or {}).get("attributes") or {}
        if not attributes:
            raise CandidateNotFound("DataCite record was missing")
        authors = "; ".join(
            author.get("name") for author in attributes.get("creators", []) if author.get("name")
        )
        abstract = next(
            (
                _clean_markup(item.get("description"))
                for item in attributes.get("descriptions", [])
                if item.get("descriptionType") == "Abstract"
            ),
            None,
        )
        canonical_doi = _first(attributes.get("doi")) or value
        resource_type = attributes.get("types", {})
        publisher = _first(attributes.get("publisher"))
        urls = _collect_urls(f"https://doi.org/{canonical_doi}", _first(attributes.get("url")))
        keywords = (
            "; ".join(
                item.get("subject")
                for item in attributes.get("subjects", [])
                if item.get("subject")
            )
            or None
        )
        return ProviderRecord(
            title=_clean_markup(
                _first([item.get("title") for item in attributes.get("titles", [])])
            )
            or "",
            abstract=abstract,
            authors=authors or None,
            keywords=keywords,
            publication_date=_first(
                attributes.get("published") or attributes.get("publicationYear")
            ),
            publication_title=publisher,
            publisher=publisher,
            doi=canonical_doi,
            urls=urls,
            identifiers=json.dumps({"doi": canonical_doi}),
            reference_type=normalize_reference_type(
                resource_type.get("resourceType") or resource_type.get("resourceTypeGeneral")
            ),
        )


DATACITE_PROVIDER = ProviderDefinition(
    name="datacite",
    identifier_aliases=("datacite",),
    identifier_parser=parse_doi,
    lookup_adapter=DataCiteLookupAdapter(),
    endpoint="https://api.datacite.org/dois",
)
