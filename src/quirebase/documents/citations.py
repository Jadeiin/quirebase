from __future__ import annotations

from typing import TYPE_CHECKING

from quirebase.access.items import require_readable_item
from quirebase.core.errors import ValidationFailure
from quirebase.discovery.bibliography import SUPPORTED_FORMATS, export_bibliography

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from quirebase.models import User


def get_item_citation_response(
    db: Session, user: User, item_id: str, file_format: str
) -> tuple[str, str, str]:
    item = require_readable_item(db, user, item_id)
    export_format = "ris" if file_format == "endnote" else file_format
    if export_format not in SUPPORTED_FORMATS:
        raise ValidationFailure("format must be bibtex, ris, or endnote")
    contents = export_bibliography([item], export_format)
    media_type = (
        "application/x-bibtex"
        if export_format == "bibtex"
        else "application/x-research-info-systems"
    )
    extension = {"bibtex": "bib", "ris": "ris", "endnote": "enw"}[file_format]
    filename = f"quirebase-export.{extension}"
    return contents, media_type, filename
