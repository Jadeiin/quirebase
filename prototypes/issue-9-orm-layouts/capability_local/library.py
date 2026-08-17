from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class Item(Base):
    __tablename__ = "items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    creator: Mapped["User"] = relationship()
    revisions: Mapped[list["FileRevision"]] = relationship(back_populates="item")
