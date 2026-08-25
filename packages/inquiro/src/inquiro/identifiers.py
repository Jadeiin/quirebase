from __future__ import annotations

import re
from typing import TYPE_CHECKING

from inquiro.models import Identifier, InvalidProviderRequest

if TYPE_CHECKING:
    from inquiro.providers._contracts import ProviderDefinition

DOI_PATTERN = re.compile(r"10\.\d{4,9}/\S+", re.IGNORECASE)
PMID_PATTERN = re.compile(r"\d{1,10}")
PMCID_PATTERN = re.compile(r"PMC\d+", re.IGNORECASE)
ISBN_PATTERN = re.compile(r"(?:97[89])?\d{9}[\dX]", re.IGNORECASE)
ARXIV_PATTERN = re.compile(
    r"(?:[a-z-]+(?:\.[A-Z]{2})?/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE
)
OPENALEX_PATTERN = re.compile(r"W\d+", re.IGNORECASE)
BIBCODE_PATTERN = re.compile(r"\d{4}[A-Za-z0-9.&]{5,20}")
ARTICLE_NUMBER_PATTERN = re.compile(r"\d{1,12}")


def normalize_doi(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"^doi:\s*", "", cleaned, flags=re.IGNORECASE)


def parse_doi(candidate: str, alias: str) -> Identifier | None:
    if not DOI_PATTERN.fullmatch(candidate):
        return None
    provider = alias if alias in ("crossref", "datacite") else "doi"
    return Identifier(provider, candidate.rstrip(".,; "))


def parse_pmid(candidate: str, _alias: str) -> Identifier | None:
    value = re.sub(r"^pmid:\s*", "", candidate, flags=re.IGNORECASE)
    return Identifier("pmid", value) if PMID_PATTERN.fullmatch(value) else None


def parse_pmcid(candidate: str, alias: str) -> Identifier | None:
    value = re.sub(r"^pmcid?:\s*", "", candidate, flags=re.IGNORECASE)
    if value.isdigit() and alias in {"pmc", "pmcid"}:
        value = f"PMC{value}"
    return Identifier("pmc", value.upper()) if PMCID_PATTERN.fullmatch(value) else None


def parse_arxiv(candidate: str, _alias: str) -> Identifier | None:
    value = re.sub(
        r"^(?:https?://arxiv\.org/(?:abs|pdf)/|arxiv:\s*)",
        "",
        candidate,
        flags=re.IGNORECASE,
    ).removesuffix(".pdf")
    return Identifier("arxiv", value) if ARXIV_PATTERN.fullmatch(value) else None


def parse_isbn(candidate: str, _alias: str) -> Identifier | None:
    value = re.sub(r"^(?:urn:isbn:|isbn(?:-1[03])?:?)\s*", "", candidate, flags=re.IGNORECASE)
    value = re.sub(r"[-\s]", "", value)
    return Identifier("isbn", value.upper()) if ISBN_PATTERN.fullmatch(value) else None


def parse_openalex(candidate: str, _alias: str) -> Identifier | None:
    value = re.sub(r"^https?://openalex\.org/", "", candidate, flags=re.IGNORECASE)
    if OPENALEX_PATTERN.fullmatch(value):
        return Identifier("openalex", value.upper())
    if DOI_PATTERN.fullmatch(candidate):
        return Identifier("openalex", candidate.rstrip(".,; "))
    return None


def parse_bibcode(candidate: str, _alias: str) -> Identifier | None:
    value = re.sub(r"^bibcode:\s*", "", candidate, flags=re.IGNORECASE)
    return Identifier("bibcode", value) if BIBCODE_PATTERN.fullmatch(value) else None


def parse_article_number(candidate: str, _alias: str) -> Identifier | None:
    value = re.sub(r"^(?:article_number|ieee):\s*", "", candidate, flags=re.IGNORECASE)
    return Identifier("article_number", value) if ARTICLE_NUMBER_PATTERN.fullmatch(value) else None


def parse_identifier(
    value: str,
    provider: str,
    *,
    registrations: tuple[ProviderDefinition, ...],
) -> Identifier:
    aliases = tuple(
        alias for registration in registrations for alias in registration.identifier_aliases
    )
    if provider != "auto" and provider not in aliases:
        choices = ", ".join(aliases[:-1]) + f" or {aliases[-1]}"
        raise InvalidProviderRequest(f"provider must be auto, {choices}")
    candidate = normalize_doi(value)
    if not candidate or len(candidate) > 500 or any(ord(character) < 32 for character in candidate):
        raise InvalidProviderRequest("identifier is invalid")
    selected = (
        registrations
        if provider == "auto"
        else tuple(
            registration
            for registration in registrations
            if provider in registration.identifier_aliases
        )
    )
    for registration in selected:
        if provider == "auto" and not registration.auto_detect_identifier:
            continue
        parser = registration.identifier_parser
        if parser is not None and (identifier := parser(candidate, provider)) is not None:
            return identifier
    if provider != "auto":
        raise InvalidProviderRequest(f"identifier is not a valid {provider}")
    raise InvalidProviderRequest(
        "identifier is not a recognized DOI, PMID, PMCID, arXiv ID, ISBN or OpenAlex ID"
    )
