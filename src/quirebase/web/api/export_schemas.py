from pydantic import BaseModel


class CitationKeyPreviewView(BaseModel):
    key: str


class AnnotationExportCreatedView(BaseModel):
    id: str
    state: str
    status_url: str
