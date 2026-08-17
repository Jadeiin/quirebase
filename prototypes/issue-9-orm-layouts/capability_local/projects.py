from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class ProjectItem(Base):
    __tablename__ = "project_items"
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"), primary_key=True)
