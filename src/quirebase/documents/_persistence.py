"""Document values persisted by authorized commands and durable transactions."""

from quirebase.core.persistence import Repository, Service
from quirebase.models import (
    Attachment,
    ExportArtifact,
    FileRevision,
    PdfAnnotation,
    PdfAnnotationReply,
)


class FileRevisionRepository(Repository[FileRevision]):
    model_type = FileRevision


class FileRevisionService(Service[FileRevision]):
    repository_type = FileRevisionRepository


class AttachmentRepository(Repository[Attachment]):
    model_type = Attachment


class AttachmentService(Service[Attachment]):
    repository_type = AttachmentRepository


class ExportArtifactRepository(Repository[ExportArtifact]):
    model_type = ExportArtifact
    id_attribute = "workflow_id"


class ExportArtifactService(Service[ExportArtifact]):
    repository_type = ExportArtifactRepository


class AnnotationRepository(Repository[PdfAnnotation]):
    model_type = PdfAnnotation


class AnnotationService(Service[PdfAnnotation]):
    repository_type = AnnotationRepository


class AnnotationReplyRepository(Repository[PdfAnnotationReply]):
    model_type = PdfAnnotationReply


class AnnotationReplyService(Service[PdfAnnotationReply]):
    repository_type = AnnotationReplyRepository
