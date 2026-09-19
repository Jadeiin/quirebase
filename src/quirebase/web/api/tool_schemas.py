from pydantic import BaseModel, Field

from quirebase.web.api.library_schemas import ItemSearchView


class CitationStyleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    csl: str = Field(min_length=1)


class TagMergeRequest(BaseModel):
    source_tag_id: str
    target_tag_id: str


class DuplicatesReviewView(BaseModel):
    groups: list[list[ItemSearchView]]
