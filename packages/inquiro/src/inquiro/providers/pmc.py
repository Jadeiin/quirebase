from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING
from urllib.parse import urlsplit
from xml.etree import ElementTree

from commonmeta.base_utils import compact

from inquiro.canonical import clean_rich_markup, first_text
from inquiro.identifiers import parse_pmcid
from inquiro.models import (
    AcquiredDocument,
    CandidatePage,
    CandidateRecord,
    Identifier,
    PdfNotAvailable,
    ProviderConfig,
    ProviderUnavailable,
    SearchQuery,
)
from inquiro.providers._contracts import ProviderDefinition, RemoteNotFound
from inquiro.providers._payload import (
    ncbi_contributors,
    ncbi_summaries,
    source_identifiers,
    source_work_id,
)

if TYPE_CHECKING:
    from inquiro.transport import BoundedTransport


class PmcSearchAdapter:
    async def search(
        self,
        client: BoundedTransport,
        request: SearchQuery,
        *,
        settings: ProviderConfig,
        endpoint: str,
    ) -> CandidatePage:
        total, summaries = await ncbi_summaries(client, request, settings, endpoint, "pmc")
        results = []
        for _uid, summary in summaries:
            title = clean_rich_markup(summary.get("title"))
            if not title:
                continue
            identities = {
                entry["idtype"]: entry["value"]
                for entry in summary.get("articleids", [])
                if entry.get("idtype") in {"doi", "pmid"} and entry.get("value")
            }
            if not identities:
                continue
            namespace = "doi" if "doi" in identities else "pmid"
            identity = Identifier(namespace, identities[namespace])
            results.append(
                CandidateRecord(
                    provider="pmc",
                    lookup_identifier=identity,
                    work=compact({
                        "id": source_work_id(
                            tuple((Identifier(key, value) for key, value in identities.items()))
                        ),
                        "type": "JournalArticle",
                        "title": title,
                        "contributors": ncbi_contributors(summary),
                        "date_published": first_text(summary.get("pubdate")),
                        "identifiers": source_identifiers(
                            tuple((Identifier(key, value) for key, value in identities.items()))
                        ),
                        "container": compact({
                            "title": first_text(
                                summary.get("fulljournalname") or summary.get("source")
                            )
                        }),
                    }),
                )
            )
        return CandidatePage("pmc", tuple(results), total, request.page, request.per_page)


class PmcDocumentAdapter:
    async def acquire(
        self, client: BoundedTransport, value: str, settings: ProviderConfig, *, endpoint: str
    ) -> AcquiredDocument:
        listing = await client.get(
            endpoint, {"list-type": "2", "prefix": f"{value}.", "delimiter": "/", "max-keys": "100"}
        )
        try:
            root = ElementTree.fromstring(listing)
        except ElementTree.ParseError as error:
            raise ProviderUnavailable("PMC returned an invalid article-version listing") from error
        versions = [
            (int(match.group(1)), prefix)
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == "Prefix"
            and (prefix := (element.text or "").strip())
            and (match := re.fullmatch(f"{re.escape(value)}\\.(\\d+)/", prefix))
        ]
        if not versions:
            raise PdfNotAvailable("PMC article dataset was not found")
        _version, prefix = max(versions)
        version_key = prefix.removesuffix("/")
        try:
            metadata = json.loads(await client.get(f"{endpoint}/metadata/{version_key}.json"))
            if not isinstance(metadata, dict):
                raise TypeError
        except RemoteNotFound as error:
            raise PdfNotAvailable("PMC article metadata was not found") from error
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("PMC returned invalid article metadata") from error
        pdf_url = first_text(metadata.get("pdf_url"))
        if not pdf_url:
            raise PdfNotAvailable("PMC article version does not include a PDF")
        parsed = urlsplit(pdf_url)
        if parsed.scheme != "s3" or parsed.netloc != "pmc-oa-opendata":
            raise ProviderUnavailable("PMC returned an invalid PDF location")
        return await client.download_pdf(
            f"https://{parsed.netloc}.s3.amazonaws.com{parsed.path}",
            filename=f"{version_key}.pdf",
            provider="pmc",
        )


PMC_PROVIDER = ProviderDefinition(
    name="pmc",
    display_name="PMC",
    identifier_namespace="pmcid",
    identifier_parser=parse_pmcid,
    auto_detect_identifier=True,
    search_adapter=PmcSearchAdapter(),
    document_adapter=PmcDocumentAdapter(),
    endpoint="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
    document_endpoint="https://pmc-oa-opendata.s3.amazonaws.com",
)
