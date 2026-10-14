"""Consume the external Commonmeta Work contract without a parallel metadata model."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any
from urllib.parse import quote, urlsplit

import jsonschema_rs
from commonmeta import Metadata
from commonmeta.author_utils import HumanName
from commonmeta_schema import schema_path
from pydantic import BaseModel, model_serializer, model_validator

from inquiro._commonmeta_adapters import reader_input
from inquiro.identifiers import (
    OPENALEX_PATTERN,
    canonical_doi,
    parse_arxiv,
    parse_bibcode,
    parse_doi,
    parse_ieee,
    parse_isbn,
    parse_openalex,
    parse_pmcid,
    parse_pmid,
)


class InvalidWork(ValueError):
    """A payload does not satisfy the external Work contract."""


class WorkContract(BaseModel):
    """Generated Work's base: enforce official rules beyond Python type hints."""

    @model_validator(mode="before")
    @classmethod
    def validate_contract(cls, value: Any) -> Any:
        return validate_work(value)

    @model_serializer(mode="wrap")
    def serialize_contract(self, handler):
        # Generated optional Python fields default to None; the standard omits
        # absent properties rather than emitting schema-invalid JSON nulls.
        def omit_none(value):
            if isinstance(value, dict):
                return {key: omit_none(item) for key, item in value.items() if item is not None}
            if isinstance(value, list):
                return [omit_none(item) for item in value]
            return value

        return omit_none(handler(self))


@lru_cache(maxsize=1)
def work_schema() -> dict[str, Any]:
    return json.loads(schema_path("1.0").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _validator():
    # Preserve the official definitions and references. Validate a Work, not a
    # person/organization that also happens to satisfy the entity root.
    return jsonschema_rs.validator_for(
        {key: work_schema()[key] for key in ("$schema", "$id", "$defs")} | {"$ref": "#/$defs/work"},
        validate_formats=True,
    )


def validate_work(work: dict[str, Any]) -> dict[str, Any]:
    errors = list(_validator().iter_errors(work))
    if errors:
        raise InvalidWork(str(errors[0]))
    return json.loads(json.dumps(work))


def read_work(payload: Any, source: str) -> dict[str, Any]:
    """Convert an explicitly fetched/local payload; never resolve identifiers."""
    try:
        payload, reader_source = reader_input(payload, source)
        metadata = Metadata(payload, via=reader_source, no_network=True)
        result = metadata.write(to="commonmeta")
    except ValueError as error:
        raise InvalidWork(str(error)) from error
    except (AttributeError, IndexError, KeyError, TypeError) as error:
        # UPSTREAM(commonmeta-py 0.309): readers assume source-specific shapes. Report conversion
        # failures at this boundary so one malformed input remains one record.
        raise InvalidWork(f"{source} reader could not convert the record: {error}") from error
    if result is None:
        raise InvalidWork("metadata conversion returned no Work")
    work = json.loads(result)
    if source == "csl" and payload.get("editor"):
        # UPSTREAM(commonmeta-py 0.309): the CSL reader assigns Author to editors.
        from commonmeta.author_utils import get_authors
        from commonmeta.utils import from_csl

        authors = get_authors(from_csl(payload.get("author", [])))
        editors = get_authors(from_csl(payload["editor"]))
        for credit in editors:
            credit["roles"] = ["Editor"]
        work["contributors"] = [*authors, *editors]
    return work


def writer_work(work: dict[str, Any]) -> dict[str, Any]:
    """Temporary writer input: select the active credit entity and the Work DOI."""
    return _writer_work(validate_work(work))


def _writer_work(result: dict[str, Any]) -> dict[str, Any]:
    """Prepare an owned, validated Work snapshot for the upstream writers."""
    if doi := work_doi(result):
        # UPSTREAM(commonmeta-py 0.309): writers read DOI from id only, ignoring identifiers.
        # Keep the resolver URI valid without changing the raw DOI selected
        # from the Work; format adapters restore that raw DOI in DOI fields.
        result["id"] = f"https://doi.org/{quote(doi, safe='/')}"
    container = result.get("container", {})
    if result["type"] == "JournalArticle" and container.get("title") and not container.get("type"):
        # UPSTREAM(commonmeta-py 0.309): BibTeX requires the Journal discriminator even
        # though Work's container permits an omitted discriminator.
        result["container"] = {**container, "type": "Journal"}
    # UPSTREAM(commonmeta-py 0.309): name writers prefer Person regardless of type.
    # Select on a temporary copy; lossless Commonmeta export keeps both snapshots.
    for credit in result.get("contributors", []):
        credit.pop("organization" if credit["type"] == "Person" else "person", None)
        if credit["type"] == "Person":
            person = credit["person"]
            if person.get("name") and not (person.get("family_name") or person.get("given_name")):
                # UPSTREAM(commonmeta-py 0.309): writers ignore name-only Person credits.
                name = HumanName(person["name"])
                # A mononym has no split family name, but the text writers
                # require one. Preserve it as a single output name.
                person["family_name"] = name.last or person["name"]
                if name.last and (
                    given := " ".join(part for part in (name.first, name.middle) if part)
                ):
                    person["given_name"] = given
    return result


def contributor_suffix(credit: dict[str, Any]) -> str | None:
    """Recover a suffix from the standard full name without changing stored name parts."""
    # UPSTREAM(commonmeta-py 0.309): citation writers use name parts and lose
    # suffixes retained only in person.name, including PubMed Jr./Sr. credits.
    if credit["type"] != "Person":
        return None
    person = credit.get("person", {})
    if not person.get("name") or not person.get("family_name"):
        return None
    name = HumanName(person["name"])
    given = " ".join(part for part in (name.first, name.middle) if part)
    if name.last == person["family_name"] and given == person.get("given_name", ""):
        return name.suffix or None
    return None


def normalize_identifier(namespace: str, value: str) -> tuple[str, str] | None:
    """Comparison keys for existing supported lookup namespaces; no identity claims."""
    namespace = namespace.strip().lower()
    value = value.strip()
    if not value:
        return None
    if namespace == "doi":
        parsed_doi = parse_doi(canonical_doi(value), namespace)
        return (namespace, canonical_doi(parsed_doi.value)) if parsed_doi else None
    # These are the existing Inquiro lookup parsers, rather than a new registry.
    parsed = None
    if namespace == "arxiv":
        parsed = parse_arxiv(value, namespace)
    elif namespace == "pmid":
        parsed = parse_pmid(value, namespace)
    elif namespace == "pmcid":
        parsed = parse_pmcid(value, namespace)
    elif namespace == "isbn":
        parsed = parse_isbn(value, namespace)
    elif namespace == "openalex":
        parsed = parse_openalex(value, namespace)
        if parsed and not OPENALEX_PATTERN.fullmatch(parsed.value):
            parsed = None
    elif namespace == "bibcode":
        parsed = parse_bibcode(value, namespace)
    elif namespace == "ieee":
        parsed = parse_ieee(value, namespace)
    return (namespace, parsed.value) if parsed is not None else None


def work_identifiers(work: dict[str, Any]) -> set[tuple[str, str]]:
    """Only the Work's own identifiers participate in lookup and suggestions."""
    pairs = set()
    for row in work.get("identifiers", []):
        namespace = (
            row.get("scheme", "") if row["identifier_type"] == "Other" else row["identifier_type"]
        )
        if pair := normalize_identifier(namespace, row["identifier"]):
            pairs.add(pair)
    resource_id = work.get("id", "")
    uri = urlsplit(resource_id)
    namespace = None
    value = resource_id
    if uri.hostname in {"doi.org", "dx.doi.org"}:
        namespace = "doi"
    elif uri.hostname == "openalex.org" and uri.path.upper().startswith("/W"):
        namespace = "openalex"
    elif uri.hostname in {"arxiv.org", "www.arxiv.org"}:
        namespace = "arxiv"
    elif uri.hostname == "pubmed.ncbi.nlm.nih.gov":
        namespace, value = "pmid", uri.path.strip("/")
    elif uri.hostname in {"pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"}:
        parts = uri.path.strip("/").split("/")
        if uri.hostname == "pmc.ncbi.nlm.nih.gov" and len(parts) == 2 and parts[0] == "articles":
            namespace, value = "pmcid", parts[1]
        elif uri.hostname == "www.ncbi.nlm.nih.gov":
            if len(parts) == 3 and parts[:2] == ["pmc", "articles"]:
                namespace, value = "pmcid", parts[2]
            elif len(parts) == 2 and parts[0] == "pubmed":
                namespace, value = "pmid", parts[1]
    elif resource_id.lower().startswith("urn:isbn:"):
        namespace = "isbn"
    if namespace and (pair := normalize_identifier(namespace, value)):
        pairs.add(pair)
    return pairs


def work_id_identifier(resource_id: str) -> dict[str, str]:
    """Represent an existing primary URI as a standard Work identifier."""
    types = work_schema()["$defs"]["identifier"]["properties"]["identifier_type"]["enum"]
    if pairs := work_identifiers({"id": resource_id}):
        namespace, value = next(iter(pairs))
        kind = next((kind for kind in types if kind.lower() == namespace), "Other")
        return {
            "identifier_type": kind,
            # These existing parsers accept resolver URLs; preserve the source
            # URI, including Commonmeta's OpenAlex URL form.
            "identifier": resource_id if namespace in {"doi", "arxiv", "openalex"} else value,
            **({"scheme": namespace} if kind == "Other" else {}),
        }
    from commonmeta.utils import validate_id

    _, kind = validate_id(resource_id)
    return {
        "identifier_type": kind
        if kind in types
        else "URN"
        if urlsplit(resource_id).scheme == "urn"
        else "URL",
        "identifier": resource_id,
    }


def work_doi(work: dict[str, Any]) -> str | None:
    if urlsplit(work.get("id", "")).hostname in {"doi.org", "dx.doi.org"} and (
        primary := normalize_identifier("doi", work["id"])
    ):
        return primary[1]
    return next(
        (value for namespace, value in sorted(work_identifiers(work)) if namespace == "doi"), None
    )


def contributor_name(contributor: dict[str, Any]) -> str:
    entity = contributor.get(contributor["type"].lower(), {})
    return entity.get("name") or ", ".join(
        part for part in (entity.get("family_name"), entity.get("given_name")) if part
    )


def work_authors(work: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in work.get("contributors", []) if "Author" in row.get("roles", [])]
