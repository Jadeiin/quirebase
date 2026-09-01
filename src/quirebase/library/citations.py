from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from inquiro.bibliography import (
    BIBLIOGRAPHY_EXTENSIONS,
    BIBLIOGRAPHY_MEDIA_TYPES,
    DEFAULT_CITATION_KEY_FORMULA,
    SUPPORTED_FORMATS,
    BibliographyExportOptions,
    BibliographyRecord,
    CitationEngineUnavailable,
    CitationKeyFormulaError,
    CitationStyleOption,
    CitationStyleSelection,
    InvalidExportOptions,
    builtin_style_xml,
    export_bibliography_records,
    is_valid_csl,
    record_to_csl_json,
    render_bibliography,
    render_citation,
    select_builtin_citation_styles,
)
from inquiro.bibliography import (
    Contributor as BibliographyContributor,
)
from inquiro.bibliography import (
    preview_citation_key as preview_formula,
)
from sqlalchemy import select

from quirebase.access.items import require_readable_item
from quirebase.core.errors import ResourceNotFound, ValidationFailure
from quirebase.models import CitationStyle

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import Item, User


def preview_citation_key(formula: str, *, force_ascii: bool = False) -> str:
    if len(formula) > 1000:
        raise ValidationFailure("citation key formula is too long")
    try:
        return preview_formula(formula, force_ascii=force_ascii)
    except CitationKeyFormulaError as error:
        raise ValidationFailure(str(error)) from error


async def resolve_style_xml(db: AsyncSession, user: User | None, style_key: str) -> str | None:
    builtin = await asyncio.to_thread(builtin_style_xml, style_key)
    if builtin:
        return builtin
    if user is None:
        return None
    style = await db.get(CitationStyle, style_key)
    if style is None or style.created_by != user.id:
        return None
    return style.csl_xml


async def list_custom_citation_styles(db: AsyncSession, user: User) -> list[CitationStyle]:
    return list(
        (
            await db.scalars(
                select(CitationStyle)
                .where(CitationStyle.created_by == user.id)
                .order_by(CitationStyle.name)
            )
        ).all()
    )


async def create_custom_citation_style(
    db: AsyncSession, user: User, name: str, csl: str
) -> CitationStyle:
    name = name.strip()
    if not name:
        raise ValidationFailure("style name is required")
    if len(name) > 120:
        name = name[:120]
    if not is_valid_csl(csl):
        raise ValidationFailure("the CSL text is not a valid citation style")
    style = CitationStyle(name=name, csl_xml=csl, created_by=user.id)
    db.add(style)
    await db.commit()
    return style


async def delete_custom_citation_style(db: AsyncSession, user: User, style_id: str) -> None:
    style = await db.get(CitationStyle, style_id)
    if style is None or style.created_by != user.id:
        raise ResourceNotFound("citation style not found")
    await db.delete(style)
    await db.commit()


async def format_csl_export(
    db: AsyncSession,
    user: User,
    items: list[Item],
    style_key: str = "apa",
    options: BibliographyExportOptions | None = None,
) -> tuple[str, str, str]:
    style_xml = await resolve_style_xml(db, user, style_key)
    if style_xml is None:
        raise ValidationFailure("unknown citation style")
    try:
        entries = render_bibliography(
            [
                record_to_csl_json(
                    _item_to_bibliography_record(item), options, item_id=str(item.id)
                )
                for item in items
            ],
            style_xml,
        )
    except CitationEngineUnavailable as error:
        raise ValidationFailure(str(error)) from error
    return "\n\n".join(entries), "text/plain", "quirebase-citations.txt"


def format_standard_export(
    items: list[Item], file_format: str, options: BibliographyExportOptions | None = None
) -> tuple[str, str, str]:
    if file_format not in SUPPORTED_FORMATS:
        raise ValidationFailure("format must be bibtex, biblatex, ris, or endnote")
    try:
        contents = export_bibliography_records(
            [_item_to_bibliography_record(item) for item in items],
            file_format,
            options=options,
        )
    except (InvalidExportOptions, CitationKeyFormulaError, ValueError) as error:
        raise ValidationFailure(str(error)) from error
    media_type = BIBLIOGRAPHY_MEDIA_TYPES[file_format]
    extension = BIBLIOGRAPHY_EXTENSIONS[file_format]
    filename = f"quirebase-export.{extension}"
    return contents, media_type, filename


def _json_fields(value: str | None) -> tuple[tuple[str, str], ...]:
    parsed: Any = None
    with suppress(json.JSONDecodeError, TypeError):
        parsed = json.loads(value or "{}")
    if not isinstance(parsed, dict):
        return ()
    return tuple(
        (
            str(key),
            json.dumps(field_value, ensure_ascii=False)
            if isinstance(field_value, (dict, list))
            else str(field_value),
        )
        for key, field_value in parsed.items()
        if field_value not in (None, "")
    )


def _contributors(value: str | None) -> tuple[BibliographyContributor, ...]:
    return tuple(
        BibliographyContributor.parse(part.strip())
        for part in (value or "").split(";")
        if part.strip()
    )


def _item_contributors(item: Item, role: str) -> tuple[BibliographyContributor, ...]:
    linked = tuple(
        BibliographyContributor(
            family_name=link.author.last_name,
            given_name=link.author.first_name,
        )
        for link in item.author_links
        if link.role == role
    )
    if linked:
        return linked
    cached = item.authors if role == "author" else item.editors
    return _contributors(cached)


def _item_to_bibliography_record(item: Item) -> BibliographyRecord:
    """Map the Library-owned Item explicitly onto Inquiro's neutral Interface."""
    return BibliographyRecord(
        citation_key=item.bibtex_id,
        reference_type=item.reference_type or "article",
        bibtex_type=item.bibtex_type,
        title=item.title,
        authors=_item_contributors(item, "author"),
        editors=_item_contributors(item, "editor"),
        abstract=item.abstract,
        keywords=tuple(part.strip() for part in (item.keywords or "").split(";") if part.strip()),
        publication_date=item.publication_date,
        publication_title=item.publication_title,
        journal_abbreviation=item.journal_abbreviation,
        volume=item.volume,
        issue=item.issue,
        pages=item.pages,
        publisher=item.publisher,
        location=item.place_published,
        doi=item.doi,
        urls=tuple(part.strip() for part in (item.urls or "").splitlines() if part.strip()),
        identifiers=_json_fields(item.identifiers),
        custom_fields=_json_fields(item.custom_fields),
    )


async def get_item_citation_response(
    db: AsyncSession,
    user: User,
    item_id: str,
    file_format: str,
    style_key: str = "apa",
    options: BibliographyExportOptions | None = None,
) -> tuple[str, str, str]:
    item = await require_readable_item(db, user, item_id)
    if file_format == "csl":
        return await format_csl_export(db, user, [item], style_key=style_key, options=options)
    return format_standard_export([item], file_format, options=options)


async def get_item_citation_text_response(
    db: AsyncSession, user: User, item_id: str, style_key: str = "apa", output: str = "text"
) -> tuple[str, str]:
    item = await require_readable_item(db, user, item_id)
    style_xml = await resolve_style_xml(db, user, style_key)
    if style_xml is None:
        raise ValidationFailure("unknown citation style")
    try:
        rendered = render_citation(
            _item_to_bibliography_record(item), style_xml, output_format=output
        )
    except CitationEngineUnavailable as error:
        raise ValidationFailure(str(error)) from error
    media_type = "text/html" if output == "html" else "text/plain"
    return rendered, media_type


__all__ = [
    "BIBLIOGRAPHY_EXTENSIONS",
    "BIBLIOGRAPHY_MEDIA_TYPES",
    "DEFAULT_CITATION_KEY_FORMULA",
    "BibliographyExportOptions",
    "CitationStyleOption",
    "CitationStyleSelection",
    "create_custom_citation_style",
    "delete_custom_citation_style",
    "format_csl_export",
    "format_standard_export",
    "get_item_citation_response",
    "get_item_citation_text_response",
    "list_custom_citation_styles",
    "preview_citation_key",
    "resolve_style_xml",
    "select_builtin_citation_styles",
]
