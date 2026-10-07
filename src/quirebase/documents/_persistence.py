"""Document values persisted by authorized commands and durable transactions."""

from quirebase.core.persistence import Repository
from quirebase.models import (
    Attachment,
    ExportArtifact,
    FileRevision,
    PdfAnnotation,
    PdfAnnotationReply,
)


class FileRevisionRepository(Repository[FileRevision]):
    model_type = FileRevision


class AttachmentRepository(Repository[Attachment]):
    model_type = Attachment


class ExportArtifactRepository(Repository[ExportArtifact]):
    model_type = ExportArtifact
    id_attribute = "workflow_id"


class AnnotationRepository(Repository[PdfAnnotation]):
    model_type = PdfAnnotation


class AnnotationReplyRepository(Repository[PdfAnnotationReply]):
    model_type = PdfAnnotationReply
