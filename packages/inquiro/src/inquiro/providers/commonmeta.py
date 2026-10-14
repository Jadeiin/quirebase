"""DOI lookup through the hosted Commonmeta service."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import quote

from inquiro.identifiers import canonical_doi, parse_doi
from inquiro.models import (
    CandidateRecord,
    Identifier,
    InvalidProviderRequest,
    ProviderConfig,
    ProviderUnavailable,
)
from inquiro.providers._contracts import ProviderDefinition
from inquiro.work import validate_work, work_identifiers

if TYPE_CHECKING:
    from inquiro.transport import BoundedTransport


class CommonmetaLookupAdapter:
    async def lookup(
        self,
        client: BoundedTransport,
        identifier: Identifier,
        settings: ProviderConfig,
        *,
        endpoint: str,
    ) -> CandidateRecord:
        doi = identifier.value
        # UPSTREAM(dragoman): the hosted service currently interpolates decoded DOI
        # delimiters into downstream URLs. Reject these forms until that path is fixed.
        if any(character in doi for character in "?#%"):
            raise InvalidProviderRequest(
                "Commonmeta cannot safely resolve DOI values containing ?, # or %; choose another DOI Provider"
            )
        body = await client.get(
            f"{endpoint}/{quote(doi, safe='')}",
            {"format": "commonmeta"},
            headers={"Accept": "application/vnd.commonmeta+json"},
        )
        try:
            payload = json.loads(body)
            work = validate_work(payload)
        except (ValueError, TypeError) as error:
            raise ProviderUnavailable("Commonmeta returned invalid Work metadata") from error
        # Query context never becomes a confirmed identifier. A hosted conversion
        # must return the requested DOI among its own bibliographic identities.
        if ("doi", canonical_doi(doi)) not in work_identifiers(work):
            raise ProviderUnavailable("Commonmeta returned a Work without the requested DOI")
        return CandidateRecord(provider="commonmeta", lookup_identifier=identifier, work=work)


COMMONMETA_PROVIDER = ProviderDefinition(
    name="commonmeta",
    display_name="Commonmeta",
    identifier_namespace="doi",
    identifier_parser=parse_doi,
    lookup_adapter=CommonmetaLookupAdapter(),
    endpoint="https://commonmeta.org",
)
