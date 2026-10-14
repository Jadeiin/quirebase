"""Private Provider payload helpers: OpenAlex reconstruction, Crossref dates, search queries."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from urllib.parse import quote
from uuid import uuid4

from commonmeta.author_utils import get_one_author
from commonmeta.base_utils import compact

from inquiro.canonical import clean_markup, first_text
from inquiro.models import Identifier, ProviderUnavailable
from inquiro.work import work_schema


def source_identifiers(identifiers) -> list[dict] | None:
    types = work_schema()["$defs"]["identifier"]["properties"]["identifier_type"]["enum"]
    result = []
    for row in identifiers:
        name = next((value for value in types if value.lower() == row.provider.lower()), "Other")
        result.append({
            "identifier": row.value,
            "identifier_type": name,
            **({"scheme": row.provider} if name == "Other" else {}),
        })
    return result or None


def source_work_id(identifiers) -> str:
    doi = next((row.value for row in identifiers if row.provider == "doi"), None)
    if doi:
        from inquiro.identifiers import canonical_doi

        # URI escaping is separate from the raw identifier retained in Work.identifiers.
        return f"https://doi.org/{quote(canonical_doi(doi), safe='/')}"
    return f"urn:uuid:{uuid4()}"


def source_credit(
    display_name,
    *,
    family_name=None,
    given_name=None,
    kind="unknown",
    identifiers=(),
    affiliations=None,
    is_corresponding=None,
) -> dict:
    source = compact({
        "name": display_name,
        "familyName": family_name,
        "givenName": given_name,
        "ORCID": next((row.value for row in identifiers if row.provider == "orcid"), None),
    })
    result = get_one_author(source, via="crossref" if kind == "organization" else None)
    if result is None:
        raise ProviderUnavailable("provider returned a nameless credit")
    entity = result.get("person", result.get("organization"))
    entity["name"] = display_name
    if affiliations and result["type"] == "Person":
        entity["affiliations"] = list(affiliations)
    if is_corresponding:
        result["roles"].append("CorrespondingAuthor")
    return result


def source_affiliation(name, identifiers=()) -> dict:
    result = {"name": name}
    if identifiers:
        row = next((row for row in identifiers if row.provider == "ror"), identifiers[0])
        result.update(
            identifier=row.value, identifier_type="ROR" if row.provider == "ror" else "Other"
        )
    return result


def source_link(url, *, kind="other", media_type=None) -> dict:
    return compact({"url": url, "kind": kind, "mime_type": media_type})


def source_landing_url(links) -> str | None:
    return next((row["url"] for row in links or () if row.get("kind") != "full_text"), None)


def source_files(links) -> list[dict] | None:
    return [
        compact({"url": row["url"], "mime_type": row.get("mime_type")})
        for row in links or ()
        if row.get("kind") == "full_text"
    ] or None


def unique_objects(rows):
    return tuple({json.dumps(row, sort_keys=True): row for row in rows}.values())


def source_subjects(values) -> list[dict] | None:
    return [{"subject": value} for value in values or ()] or None


if TYPE_CHECKING:
    from collections.abc import Sequence

    from inquiro.models import ProviderConfig, SearchClause, SearchQuery
    from inquiro.transport import BoundedTransport
__all__: list[str] = []


def text_contributors(values: Any) -> tuple[dict, ...] | None:
    if not isinstance(values, (list, tuple)):
        return None
    return (
        tuple(
            source_credit(display_name=name)
            for value in values
            if (name := clean_markup(first_text(value)))
        )
        or None
    )


def keyword_values(values: Any) -> tuple[str, ...] | None:
    if not isinstance(values, (list, tuple)):
        return None
    return tuple(
        dict.fromkeys(name for value in values if (name := clean_markup(first_text(value))))
    )


def unique_links(*links: dict | None) -> tuple[dict, ...]:
    return unique_objects(link for link in links if link is not None)


def affiliation_values(values: Any) -> tuple[dict, ...] | None:
    if not isinstance(values, (list, tuple)):
        return None
    affiliations = []
    for entry in values:
        if isinstance(entry, str):
            if name := clean_markup(entry):
                affiliations.append(source_affiliation(name))
            continue
        if not isinstance(entry, dict) or not (name := clean_markup(first_text(entry.get("name")))):
            continue
        identifiers = []
        if (value := first_text(entry.get("affiliationIdentifier"))) and (
            scheme := first_text(entry.get("affiliationIdentifierScheme"))
        ):
            identifiers.append(Identifier(scheme.casefold(), value))
        identifiers.extend(
            Identifier(scheme.casefold(), value)
            for identity in entry.get("id", [])
            if isinstance(identity, dict)
            and (value := first_text(identity.get("id")))
            and (scheme := first_text(identity.get("id-type")))
        )
        affiliations.append(source_affiliation(name, identifiers=tuple(identifiers)))
    return unique_objects(affiliations)


def boolean_query(
    clauses: Sequence[SearchClause], fields: dict[str, str], *, field_prefix: bool = False
) -> str:
    parts: list[str] = []
    for index, clause in enumerate(clauses):
        value = clause.term.replace('"', " ").replace("\\", " ").strip()
        field = fields.get(clause.field, fields["any"])
        tagged = f'{field}"{value}"' if field_prefix else f'"{value}"{field}'
        if clause.operator == "not":
            parts.append(f"NOT {tagged}")
        elif index and clause.operator == "or":
            parts.append(f"OR {tagged}")
        else:
            parts.append(("AND " if index else "") + tagged)
    return " ".join(parts)


async def ncbi_summaries(
    client: BoundedTransport,
    request: SearchQuery,
    settings: ProviderConfig,
    endpoint: str,
    database: str,
) -> tuple[int, list[tuple[str, dict]]]:
    query = boolean_query(
        request.clauses,
        {
            "any": "[All Fields]",
            "title": "[Title]",
            "author": "[Author]",
            "publication": "[Journal]",
            "abstract": "[Title/Abstract]",
        },
    )
    if request.year_from or request.year_to:
        query += f" AND {request.year_from or 1000}:{request.year_to or 3000}[Publication Date]"
    common = {"db": database, "retmode": "json", "tool": "inquiro"}
    if settings.contact_email:
        common["email"] = settings.contact_email
    if settings.ncbi_api_key:
        common["api_key"] = settings.ncbi_api_key
    try:
        found = json.loads(
            await client.get(
                f"{endpoint}/esearch.fcgi",
                common
                | {
                    "term": query,
                    "retstart": str((request.page - 1) * request.per_page),
                    "retmax": str(request.per_page),
                    "sort": "pub date" if request.sort == "published" else "relevance",
                },
            )
        ).get("esearchresult", {})
        identifiers = found.get("idlist", [])
        total = int(found.get("count", 0))
        if not identifiers:
            return (total, [])
        summaries = json.loads(
            await client.get(f"{endpoint}/esummary.fcgi", common | {"id": ",".join(identifiers)})
        ).get("result", {})
    except (TypeError, ValueError) as error:
        raise ProviderUnavailable("NCBI returned invalid search results") from error
    return (total, [(identifier, summaries.get(identifier, {})) for identifier in identifiers])


def ncbi_contributors(summary: dict) -> tuple[dict, ...] | None:
    if "authors" not in summary:
        return None
    return (
        tuple(
            source_credit(
                name,
                kind="organization" if author.get("authtype") == "CollectiveName" else "unknown",
            )
            for author in summary["authors"]
            if (name := clean_markup(first_text(author.get("name"))))
        )
        or None
    )
