from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)


class Item(Base):
    __tablename__ = "items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    creator: Mapped[User] = relationship()
    revisions: Mapped[list["FileRevision"]] = relationship(back_populates="item")


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class ProjectItem(Base):
    __tablename__ = "project_items"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"), primary_key=True)


class FileRevision(Base):
    __tablename__ = "file_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"))
    item: Mapped[Item] = relationship(back_populates="revisions")


class PdfAnnotation(Base):
    __tablename__ = "pdf_annotations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    file_revision_id: Mapped[str] = mapped_column(ForeignKey("file_revisions.id"))
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id"))


metadata = Base.metadata
