from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import quote

from inquiro.canonical import (
    clean_rich_markup,
    first_text,
)
from inquiro.identifiers import normalize_doi, parse_doi
from inquiro.models import (
    CandidateNotFound,
    CandidateRecord,
    Contributor,
    Identifier,
    ProviderConfig,
    ProviderUnavailable,
    ResourceLink,
)
from inquiro.providers._contracts import ProviderDefinition
from inquiro.providers._payload import affiliation_values, keyword_values, unique_links
from inquiro.reference_types import normalize_reference_type

if TYPE_CHECKING:
    from inquiro.transport import BoundedTransport


class DataCiteLookupAdapter:
    async def lookup(
        self,
        client: BoundedTransport,
        identifier: Identifier,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> CandidateRecord:
        value = identifier.value
        try:
            body = await client.get(f"{endpoint}/{quote(value, safe='')}")
            payload = json.loads(body)
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("DataCite returned invalid metadata") from error
        attributes = (payload.get("data") or {}).get("attributes") or {}
        if not attributes:
            raise CandidateNotFound("DataCite record was missing")
        authors = None
        if isinstance(attributes.get("creators"), list):
            authors = []
            for creator in attributes["creators"]:
                family = first_text(creator.get("familyName"))
                given = first_text(creator.get("givenName"))
                name = first_text(creator.get("name")) or " ".join(
                    part for part in (given, family) if part
                )
                if not name:
                    continue
                identities = tuple(
                    Identifier(scheme.casefold(), identity)
                    for entry in creator.get("nameIdentifiers", [])
                    if (scheme := first_text(entry.get("nameIdentifierScheme")))
                    and (identity := first_text(entry.get("nameIdentifier")))
                )
                name_type = creator.get("nameType")
                authors.append(
                    Contributor(
                        display_name=name,
                        family_name=family,
                        given_name=given,
                        kind="organization"
                        if name_type == "Organizational"
                        else "person"
                        if name_type == "Personal" or family or given
                        else "unknown",
                        identifiers=identities,
                        affiliations=affiliation_values(creator.get("affiliation")),
                    )
                )
        abstract = next(
            (
                clean_rich_markup(item.get("description"))
                for item in attributes.get("descriptions", [])
                if item.get("descriptionType") == "Abstract"
            ),
            None,
        )
        canonical_doi = normalize_doi(first_text(attributes.get("doi")) or value)
        resource_type = attributes.get("types", {})
        publisher = first_text(attributes.get("publisher"))
        urls = [ResourceLink(f"https://doi.org/{canonical_doi}", kind="landing_page")]
        if url := first_text(attributes.get("url")):
            urls.append(ResourceLink(url, kind="landing_page"))
        return CandidateRecord(
            provider="datacite",
            lookup_identifier=identifier,
            title=clean_rich_markup(
                first_text([item.get("title") for item in attributes.get("titles", [])])
            )
            or "",
            abstract=abstract,
            authors=tuple(authors) if authors is not None else None,
            keywords=keyword_values([
                item["subject"] for item in attributes["subjects"] if item.get("subject")
            ])
            if "subjects" in attributes
            else None,
            publication_date=first_text(
                attributes.get("published") or attributes.get("publicationYear")
            ),
            publisher=publisher,
            doi=canonical_doi,
            urls=unique_links(*urls),
            identifiers=(Identifier("doi", canonical_doi),),
            reference_type=normalize_reference_type(
                resource_type.get("resourceType"), source="datacite", default=None
            )
            or normalize_reference_type(
                resource_type.get("resourceTypeGeneral"), source="datacite"
            ),
        )


DATACITE_PROVIDER = ProviderDefinition(
    name="datacite",
    identifier_namespace="doi",
    identifier_parser=parse_doi,
    lookup_adapter=DataCiteLookupAdapter(),
    endpoint="https://api.datacite.org/dois",
)
