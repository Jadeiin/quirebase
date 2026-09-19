from pydantic import BaseModel, Field


class BibliographyExportRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list)
    file_format: str
    style: str = "apa"
    include_abstract: bool = True
    preserve_case: bool = False
    include_identifiers: bool = False
    include_custom_fields: bool = False
    encoding: str = "unicode"
    journal_mode: str = "full"
    doi_policy: str = "include"
    url_policy: str = "include"
    excluded_fields: list[str] = Field(default_factory=list)
    sort_by: str = "input"
    citation_key_formula: str = ""
    citation_key_force_ascii: bool = False


class DocumentArchiveRequest(BaseModel):
    item_ids: list[str]
    include_annotations: bool = False
    include_supplements: bool = False
    timezone: str = ""


class CitationKeyPreviewView(BaseModel):
    key: str


class AnnotationExportCreatedView(BaseModel):
    id: str
    state: str
    status_url: str
