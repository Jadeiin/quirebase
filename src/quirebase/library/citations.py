from __future__ import annotations

import asyncio
import json
from contextlib import suppress
from typing import TYPE_CHECKING, Any
from uuid import UUID

from advanced_alchemy.exceptions import NotFoundError
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
from sqlalchemy.exc import IntegrityError

from quirebase.access import ResourceAction, require_workspace_action
from quirebase.access.items import require_readable_item
from quirebase.core.errors import ResourceNotFound, ValidationFailure
from quirebase.core.persistence import Repository, Service
from quirebase.models import CitationStyle

if TYPE_CHECKING:
    from advanced_alchemy.service import ModelDictT
    from sqlalchemy.ext.asyncio import AsyncSession

    from quirebase.models import Item, User


class CitationStyleRepository(Repository[CitationStyle]):
    model_type = CitationStyle

    async def add_if_name_available(self, style: CitationStyle) -> CitationStyle | None:
        if await self.exists(workspace_id=style.workspace_id, name=style.name):
            return None
        try:
            async with self.session.begin_nested():
                return await self.add(style)
        except IntegrityError:
            if not await self.exists(workspace_id=style.workspace_id, name=style.name):
                raise
            return None


class CitationStyleService(Service[CitationStyle]):
    repository_type = CitationStyleRepository
    repository: CitationStyleRepository

    async def to_model_on_create(self, data: ModelDictT[CitationStyle]) -> CitationStyle:
        style = await self.to_model(data)
        style.name = style.name.strip()[:120]
        if not style.name:
            raise ValidationFailure("style name is required")
        if not is_valid_csl(style.csl_xml):
            raise ValidationFailure("the CSL text is not a valid citation style")
        return style

    async def install(
        self, workspace_id: UUID, actor_id: UUID, name: str, csl: str
    ) -> CitationStyle:
        style = await self.to_model(
            {"workspace_id": workspace_id, "created_by": actor_id, "name": name, "csl_xml": csl},
            "create",
        )
        installed = await self.repository.add_if_name_available(style)
        if installed is None:
            raise ValidationFailure("citation style name already exists in Workspace") from None
        return installed


def preview_citation_key(formula: str, *, force_ascii: bool = False) -> str:
    if len(formula) > 1000:
        raise ValidationFailure("citation key formula is too long")
    try:
        return preview_formula(formula, force_ascii=force_ascii)
    except CitationKeyFormulaError as error:
        raise ValidationFailure(str(error)) from error


async def resolve_style_xml(
    db: AsyncSession, user: User | None, workspace_id: UUID, style_key: str
) -> str | None:
    builtin = await asyncio.to_thread(builtin_style_xml, style_key)
    if builtin:
        return builtin
    if user is None:
        return None
    await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    try:
        style_id = UUID(style_key)
    except ValueError:
        return None
    style = await CitationStyleService(db).get_one_or_none(id=style_id, workspace_id=workspace_id)
    if style is None:
        return None
    return style.csl_xml


async def list_custom_citation_styles(
    db: AsyncSession, user: User, workspace_id: UUID
) -> list[CitationStyle]:
    await require_workspace_action(db, user, workspace_id, ResourceAction.workspace_read)
    styles = await CitationStyleService(db).get_many(
        CitationStyle.workspace_id == workspace_id,
        order_by=[("name", False), ("id", False)],
    )
    return list(styles)


async def create_custom_citation_style(
    db: AsyncSession, user: User, workspace_id: UUID, name: str, csl: str
) -> CitationStyle:
    await require_workspace_action(db, user, workspace_id, ResourceAction.citation_style_manage)
    style = await CitationStyleService(db).install(workspace_id, user.id, name, csl)
    await db.commit()
    return style


async def delete_custom_citation_style(
    db: AsyncSession, user: User, workspace_id: UUID, style_id: UUID
) -> None:
    await require_workspace_action(db, user, workspace_id, ResourceAction.citation_style_manage)
    service = CitationStyleService(
        db, statement=select(CitationStyle).where(CitationStyle.workspace_id == workspace_id)
    )
    style = await service.get_one_or_none(id=style_id, with_for_update=True)
    if style is None:
        raise ResourceNotFound("citation style not found")
    try:
        await service.delete(style.id)
    except NotFoundError as error:
        raise ResourceNotFound("citation style not found") from error
    await db.commit()


async def format_csl_export(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    items: list[Item],
    style_key: str = "apa",
    options: BibliographyExportOptions | None = None,
) -> tuple[str, str, str]:
    style_xml = await resolve_style_xml(db, user, workspace_id, style_key)
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
    return _field_pairs(parsed)


def _field_pairs(parsed: dict | None) -> tuple[tuple[str, str], ...]:
    return tuple(
        (
            str(key),
            json.dumps(field_value, ensure_ascii=False)
            if isinstance(field_value, (dict, list))
            else str(field_value),
        )
        for key, field_value in (parsed or {}).items()
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
        custom_fields=_field_pairs(item.custom_fields),
    )


async def get_item_citation_response(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    file_format: str,
    style_key: str = "apa",
    options: BibliographyExportOptions | None = None,
) -> tuple[str, str, str]:
    item = await require_readable_item(db, user, workspace_id, item_id)
    if file_format == "csl":
        return await format_csl_export(
            db, user, workspace_id, [item], style_key=style_key, options=options
        )
    return format_standard_export([item], file_format, options=options)


async def get_item_citation_text_response(
    db: AsyncSession,
    user: User,
    workspace_id: UUID,
    item_id: UUID,
    style_key: str = "apa",
    output: str = "text",
) -> tuple[str, str]:
    item = await require_readable_item(db, user, workspace_id, item_id)
    style_xml = await resolve_style_xml(db, user, workspace_id, style_key)
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
