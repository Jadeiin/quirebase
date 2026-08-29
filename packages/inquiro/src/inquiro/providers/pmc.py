from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

from inquiro.canonical import (
    clean_rich_markup,
    first_text,
)
from inquiro.identifiers import parse_pmcid
from inquiro.models import (
    AcquiredDocument,
    PdfNotAvailable,
    ProviderSearchPage,
    ProviderSearchRecord,
    ProviderUnavailable,
    SearchClause,
)
from inquiro.providers._contracts import ProviderContext, ProviderDefinition, RemoteNotFound
from inquiro.providers._payload import (
    boolean_query,
)


class PmcSearchAdapter:
    def search(
        self,
        client: ProviderContext,
        clauses: list[SearchClause],
        *,
        page: int,
        per_page: int,
        sort: str,
        year_from: int | None,
        year_to: int | None,
        settings: Any,
        endpoint: str,
    ) -> ProviderSearchPage:
        query = boolean_query(
            clauses,
            {
                "any": "[All Fields]",
                "title": "[Title]",
                "author": "[Author]",
                "publication": "[Journal]",
                "abstract": "[Title/Abstract]",
            },
        )
        if year_from or year_to:
            query += f" AND {year_from or 1000}:{year_to or 3000}[Publication Date]"
        params = {
            "db": "pmc",
            "term": query,
            "retmode": "json",
            "retstart": str((page - 1) * per_page),
            "retmax": str(per_page),
            "sort": "pub date" if sort == "published" else "relevance",
            "tool": "inquiro",
        }
        contact = settings.contact_email
        if contact:
            params["email"] = contact
        api_key = getattr(settings, "ncbi_api_key", None)
        if api_key:
            params["api_key"] = api_key
        try:
            found = json.loads(client._get(f"{endpoint}/esearch.fcgi", params)).get(
                "esearchresult", {}
            )
            identifiers = found.get("idlist", [])
            if not identifiers:
                return ProviderSearchPage("pmc", [], int(found.get("count", 0)), page, per_page)
            summary_params = {
                "db": "pmc",
                "id": ",".join(identifiers),
                "retmode": "json",
                "tool": "inquiro",
            }
            if contact:
                summary_params["email"] = contact
            if api_key:
                summary_params["api_key"] = api_key
            payload = json.loads(client._get(f"{endpoint}/esummary.fcgi", summary_params)).get(
                "result", {}
            )
        except (json.JSONDecodeError, TypeError) as error:
            raise ProviderUnavailable("PMC returned invalid search results") from error
        results = []
        for identifier in identifiers:
            record = payload.get(identifier, {})
            title = clean_rich_markup(record.get("title"))
            if not title:
                continue
            doi = None
            pmid = None
            for article_id in record.get("articleids", []):
                if article_id.get("idtype") == "doi" and article_id.get("value"):
                    doi = article_id["value"]
                elif article_id.get("idtype") == "pmid" and article_id.get("value"):
                    pmid = article_id["value"]
            if doi:
                result_provider, result_identifier = "doi", doi
            elif pmid:
                result_provider, result_identifier = "pmid", pmid
            else:
                continue
            results.append(
                ProviderSearchRecord(
                    provider="pmc",
                    identifier_provider=result_provider,
                    identifier=result_identifier,
                    title=title,
                    authors="; ".join(
                        author["name"] for author in record.get("authors", []) if author.get("name")
                    )
                    or None,
                    publication_title=first_text(record.get("fulljournalname") or record.get("source")),
                    publication_date=first_text(record.get("pubdate")),
                )
            )
        return ProviderSearchPage(
            "pmc", results, int(found.get("count", len(results))), page, per_page
        )


class PmcDocumentAdapter:
    def acquire(
        self,
        client: ProviderContext,
        value: str,
        settings: Any,
        *,
        endpoint: str,
    ) -> AcquiredDocument:
        listing = client._get(
            endpoint,
            {
                "list-type": "2",
                "prefix": f"{value}.",
                "delimiter": "/",
                "max-keys": "100",
            },
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
            and (match := re.fullmatch(rf"{re.escape(value)}\.(\d+)/", prefix))
        ]
        if not versions:
            raise PdfNotAvailable("PMC article dataset was not found")
        _version, prefix = max(versions)
        version_key = prefix.removesuffix("/")
        try:
            metadata = json.loads(client._get(f"{endpoint}/metadata/{version_key}.json"))
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
        return client._download_pdf(
            f"https://{parsed.netloc}.s3.amazonaws.com{parsed.path}",
            filename=f"{version_key}.pdf",
            provider="pmc",
        )


PMC_PROVIDER = ProviderDefinition(
    name="pmc",
    identifier_aliases=("pmc", "pmcid"),
    identifier_parser=parse_pmcid,
    auto_detect_identifier=True,
    search_adapter=PmcSearchAdapter(),
    document_adapter=PmcDocumentAdapter(),
    endpoint="https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
    document_endpoint="https://pmc-oa-opendata.s3.amazonaws.com",
)
