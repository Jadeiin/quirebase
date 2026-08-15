from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .core.database import Base


def uid() -> str:
    return str(uuid.uuid4())


def now() -> datetime:
    return datetime.now(UTC)


class SystemRole(StrEnum):
    administrator = "administrator"
    member = "member"


class ProjectRole(StrEnum):
    owner = "owner"
    editor = "editor"
    viewer = "viewer"


class JobState(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default=SystemRole.member.value)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    user: Mapped[User] = relationship()


class LoginThrottle(Base):
    __tablename__ = "login_throttles"
    identity_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Invitation(Base):
    __tablename__ = "invitations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(120), unique=True)
    role: Mapped[str] = mapped_column(String(32), default=SystemRole.member.value)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Item(Base):
    __tablename__ = "items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(Text, index=True)
    abstract: Mapped[str | None] = mapped_column(Text)
    publication_date: Mapped[str | None] = mapped_column(String(32))
    publication_title: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(500), index=True)
    identifiers: Mapped[str | None] = mapped_column(Text)
    reference_type: Mapped[str | None] = mapped_column(String(40))
    authors: Mapped[str | None] = mapped_column(Text)
    editors: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[str | None] = mapped_column(Text)
    custom_fields: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    revisions: Mapped[list[FileRevision]] = relationship(back_populates="item")


class ItemRead(Base):
    __tablename__ = "item_reads"
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[str] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(240))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProjectMember(Base):
    __tablename__ = "project_members"
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(16))


class ProjectItem(Base):
    __tablename__ = "project_items"
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[str] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ItemTag(Base):
    __tablename__ = "item_tags"
    item_id: Mapped[str] = mapped_column(
        ForeignKey("items.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[str] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class DiscussionMessage(Base):
    __tablename__ = "discussion_messages"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    author: Mapped[User] = relationship()


class FileRevision(Base):
    __tablename__ = "file_revisions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    object_key: Mapped[str] = mapped_column(String(200), index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/pdf")
    original_name: Mapped[str] = mapped_column(String(255))
    page_count: Mapped[int | None] = mapped_column(Integer)
    page_geometry: Mapped[str | None] = mapped_column(Text)
    full_text: Mapped[str | None] = mapped_column(Text)
    processing_state: Mapped[str] = mapped_column(String(32), default="pending")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    item: Mapped[Item] = relationship(back_populates="revisions")


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    object_key: Mapped[str] = mapped_column(String(200), index=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    original_name: Mapped[str] = mapped_column(String(255))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PdfAnnotation(Base):
    __tablename__ = "pdf_annotations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    file_revision_id: Mapped[str] = mapped_column(
        ForeignKey("file_revisions.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    scope: Mapped[str] = mapped_column(String(16), default="private")
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    color: Mapped[str] = mapped_column(String(16), default="yellow")
    body: Mapped[str | None] = mapped_column(Text)
    selected_text: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    segments: Mapped[list[PdfAnnotationSegment]] = relationship(
        back_populates="annotation",
        cascade="all, delete-orphan",
        order_by="PdfAnnotationSegment.ordinal",
    )


class PdfAnnotationSegment(Base):
    __tablename__ = "pdf_annotation_segments"
    __table_args__ = (UniqueConstraint("annotation_id", "ordinal"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    annotation_id: Mapped[str] = mapped_column(
        ForeignKey("pdf_annotations.id", ondelete="CASCADE"), index=True
    )
    page_index: Mapped[int] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer)
    x1: Mapped[float | None] = mapped_column(Float)
    y1: Mapped[float | None] = mapped_column(Float)
    x2: Mapped[float | None] = mapped_column(Float)
    y2: Mapped[float | None] = mapped_column(Float)
    x3: Mapped[float | None] = mapped_column(Float)
    y3: Mapped[float | None] = mapped_column(Float)
    x4: Mapped[float | None] = mapped_column(Float)
    y4: Mapped[float | None] = mapped_column(Float)
    anchor_x: Mapped[float | None] = mapped_column(Float)
    anchor_y: Mapped[float | None] = mapped_column(Float)
    annotation: Mapped[PdfAnnotation] = relationship(back_populates="segments")


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    state: Mapped[str] = mapped_column(String(16), default=JobState.pending.value, index=True)
    payload: Mapped[str] = mapped_column(Text)
    result: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    owner_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    file_format: Mapped[str] = mapped_column(String(16))
    records: Mapped[str] = mapped_column(Text)
    errors: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class CitationStyle(Base):
    __tablename__ = "citation_styles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    csl_xml: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(36))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
