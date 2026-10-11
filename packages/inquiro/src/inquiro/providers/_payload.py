"""Private Provider payload helpers: OpenAlex reconstruction, Crossref dates, search queries."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from inquiro.canonical import clean_markup, first_text
from inquiro.models import Affiliation, Contributor, Identifier, ProviderUnavailable, ResourceLink

if TYPE_CHECKING:
    from collections.abc import Sequence

    from inquiro.models import ProviderConfig, SearchClause, SearchQuery
    from inquiro.transport import BoundedTransport

__all__: list[str] = []


def text_contributors(values: Any) -> tuple[Contributor, ...] | None:
    if not isinstance(values, (list, tuple)):
        return None
    return tuple(
        Contributor(display_name=name)
        for value in values
        if (name := clean_markup(first_text(value)))
    )


def keyword_values(values: Any) -> tuple[str, ...] | None:
    if not isinstance(values, (list, tuple)):
        return None
    return tuple(
        dict.fromkeys(name for value in values if (name := clean_markup(first_text(value))))
    )


def unique_links(*links: ResourceLink | None) -> tuple[ResourceLink, ...]:
    return tuple(dict.fromkeys(link for link in links if link is not None))


def affiliation_values(values: Any) -> tuple[Affiliation, ...] | None:
    if not isinstance(values, (list, tuple)):
        return None
    affiliations = []
    for entry in values:
        if isinstance(entry, str):
            if name := clean_markup(entry):
                affiliations.append(Affiliation(name))
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
        affiliations.append(Affiliation(name, identifiers=tuple(identifiers)))
    return tuple(dict.fromkeys(affiliations))


def reconstruct_openalex_abstract(inverted_index: Any) -> str | None:
    if not isinstance(inverted_index, dict) or not inverted_index:
        return None
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        if isinstance(positions, list):
            word_positions.extend((pos, word) for pos in positions if isinstance(pos, int))
    if not word_positions:
        return None
    word_positions.sort(key=lambda item: item[0])
    return clean_markup(" ".join(word for _, word in word_positions))


def collect_openalex_keyword_names(*collections: Any) -> list[str]:
    names: list[str] = []
    for entries in collections:
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            name = clean_markup(first_text(entry.get("display_name")))
            if name and name not in names:
                names.append(name)
    return names


def date_parts(message: dict) -> str | None:
    parts = (
        message.get("published-print")
        or message.get("published-online")
        or message.get("issued")
        or {}
    ).get("date-parts", [])
    if not parts:
        return None
    return "-".join(
        str(number).zfill(2) if index else str(number) for index, number in enumerate(parts[0])
    )


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
            return total, []
        summaries = json.loads(
            await client.get(
                f"{endpoint}/esummary.fcgi",
                common
                | {
                    "id": ",".join(identifiers),
                },
            )
        ).get("result", {})
    except (TypeError, ValueError) as error:
        raise ProviderUnavailable("NCBI returned invalid search results") from error
    return total, [(identifier, summaries.get(identifier, {})) for identifier in identifiers]


def ncbi_contributors(summary: dict) -> tuple[Contributor, ...] | None:
    if "authors" not in summary:
        return None
    return tuple(
        Contributor(
            author["name"],
            kind="organization" if author.get("authtype") == "CollectiveName" else "unknown",
        )
        for author in summary["authors"]
        if author.get("name")
    )
