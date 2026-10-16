from __future__ import annotations

import json
from typing import TYPE_CHECKING
from urllib.parse import quote

from inquiro.identifiers import parse_doi
from inquiro.models import (
    CandidateNotFound,
    CandidateRecord,
    Identifier,
    ProviderConfig,
    ProviderUnavailable,
)
from inquiro.providers._contracts import ProviderDefinition
from inquiro.work import read_work

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
        return CandidateRecord(
            provider="datacite",
            lookup_identifier=identifier,
            work=read_work(attributes, "datacite"),
        )


DATACITE_PROVIDER = ProviderDefinition(
    name="datacite",
    display_name="DataCite",
    identifier_namespace="doi",
    identifier_parser=parse_doi,
    lookup_adapter=DataCiteLookupAdapter(),
    endpoint="https://api.datacite.org/dois",
)
