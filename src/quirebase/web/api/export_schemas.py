from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from quirebase.library import (
    DEFAULT_CITATION_KEY_FORMULA,
    BibliographyExportOptions,
    BibliographyFormat,
)


class BibliographyExportQuery(BaseModel):
    file_format: BibliographyFormat
    style: str = "apa"
    include_abstract: bool = True
    preserve_case: bool = False
    encoding: str = "unicode"
    doi_policy: str = "include"
    url_policy: str = "include"
    excluded_fields: list[str] = Field(default_factory=list)
    sort_by: str = "input"
    citation_key_formula: str = ""
    citation_key_force_ascii: bool = False

    def to_options(self) -> BibliographyExportOptions:
        return BibliographyExportOptions(
            include_abstract=self.include_abstract,
            preserve_case=self.preserve_case,
            encoding=self.encoding,
            doi_policy=self.doi_policy,
            url_policy=self.url_policy,
            excluded_fields=tuple(self.excluded_fields),
            sort_by=self.sort_by,
            citation_key_formula=self.citation_key_formula.strip() or DEFAULT_CITATION_KEY_FORMULA,
            citation_key_force_ascii=self.citation_key_force_ascii,
        )


class BibliographyExportRequest(BibliographyExportQuery):
    item_ids: list[UUID] = Field(default_factory=list)


class DocumentArchiveRequest(BaseModel):
    item_ids: list[UUID]
    include_annotations: bool = False
    include_supplements: bool = False
    timezone: str = ""


class CitationKeyPreviewView(BaseModel):
    key: str


class AnnotationExportCreatedView(BaseModel):
    id: str
    state: str
    status_url: str
