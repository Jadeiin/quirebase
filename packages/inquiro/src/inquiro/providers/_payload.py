"""Private Provider payload helpers: OpenAlex reconstruction, Crossref dates, search queries."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from inquiro.canonical import clean_markup, first_text

if TYPE_CHECKING:
    from inquiro.models import SearchClause

__all__: list[str] = []


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
    clauses: list[SearchClause], fields: dict[str, str], *, field_prefix: bool = False
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
