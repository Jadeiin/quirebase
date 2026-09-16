from __future__ import annotations

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from inquiro import (
    CandidateNotFound,
    CandidatePage,
    CandidateRecord,
    DocumentRequest,
    InvalidPdfResponse,
    InvalidProviderRequest,
    PdfAccessDenied,
    PdfNotAvailable,
    ProviderConfig,
    ProviderRuntime,
    ProviderUnavailable,
    SearchQuery,
)

from quirebase.core.errors import ResourceNotFound, UpstreamServiceError, ValidationFailure

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from quirebase.core.config import Settings


@dataclass(frozen=True)
class RemotePdf:
    content: AsyncIterator[bytes]
    filename: str
    media_type: str


def provider_config(settings: Settings) -> ProviderConfig:
    return ProviderConfig(
        timeout_seconds=settings.metadata_timeout_seconds,
        max_response_bytes=settings.metadata_max_response_bytes,
        contact_email=settings.metadata_contact_email,
        openalex_api_key=settings.openalex_api_key,
        ncbi_api_key=settings.ncbi_api_key,
        nasa_ads_token=settings.nasa_ads_token,
        ieee_api_key=settings.ieee_api_key,
    )


def provider_runtime(settings: Settings) -> ProviderRuntime:
    """Library-owned construction seam for the external Provider runtime."""
    return ProviderRuntime(provider_config(settings))


@asynccontextmanager
async def acquire_remote_pdf(
    source: str, settings: Settings, max_bytes: int
) -> AsyncIterator[RemotePdf]:
    """Acquire and validate a remote PDF through the Library Provider interface."""
    config = replace(provider_config(settings), max_document_bytes=max_bytes)
    try:
        async with (
            ProviderRuntime(config) as runtime,
            await runtime.acquire_document(DocumentRequest(source)) as document,
        ):
            yield RemotePdf(
                content=aiter(document),
                filename=document.filename,
                media_type=document.media_type,
            )
    except InvalidProviderRequest as error:
        raise ValidationFailure(str(error)) from error
    except InvalidPdfResponse as error:
        raise ValidationFailure(str(error)) from error
    except PdfNotAvailable as error:
        raise ResourceNotFound(str(error)) from error
    except (PdfAccessDenied, ProviderUnavailable) as error:
        raise UpstreamServiceError(str(error)) from error


async def lookup_candidate(
    value: str,
    provider: str,
    settings: Settings,
) -> CandidateRecord:
    try:
        async with provider_runtime(settings) as runtime:
            return await runtime.lookup(value, provider=provider)
    except InvalidProviderRequest as error:
        raise ValidationFailure(str(error)) from error
    except CandidateNotFound as error:
        raise ResourceNotFound(str(error)) from error
    except ProviderUnavailable as error:
        raise UpstreamServiceError(str(error)) from error


async def search_candidates(query: SearchQuery, settings: Settings) -> CandidatePage:
    try:
        async with provider_runtime(settings) as runtime:
            return await runtime.search(query)
    except InvalidProviderRequest as error:
        raise ValidationFailure(str(error)) from error
    except CandidateNotFound as error:
        raise ResourceNotFound(str(error)) from error
    except ProviderUnavailable as error:
        raise UpstreamServiceError(str(error)) from error


def candidate_record_values(record: CandidateRecord) -> dict[str, Any]:
    identifiers = {identifier.provider: identifier.value for identifier in record.identifiers}
    return {
        "title": record.title,
        "abstract": record.abstract,
        "authors": record.authors,
        "keywords": record.keywords,
        "publication_date": record.publication_date,
        "publication_title": record.publication_title,
        "journal_abbreviation": record.journal_abbreviation,
        "volume": record.volume,
        "issue": record.issue,
        "pages": record.pages,
        "publisher": record.publisher,
        "affiliation": record.affiliation,
        "doi": record.doi,
        "urls": record.urls,
        "identifiers": json.dumps(identifiers) if identifiers else None,
        "reference_type": record.reference_type,
    }
