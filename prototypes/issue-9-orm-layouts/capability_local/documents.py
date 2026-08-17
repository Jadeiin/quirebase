from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class FileRevision(Base):
    __tablename__ = "file_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"))
    item: Mapped["Item"] = relationship(back_populates="revisions")


class PdfAnnotation(Base):
    __tablename__ = "pdf_annotations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    file_revision_id: Mapped[str] = mapped_column(ForeignKey("file_revisions.id"))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"))
