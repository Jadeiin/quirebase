from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .core.database import Base


def uid() -> str:
    return str(uuid.uuid4())


def normalize_author_identity(last_name: str, first_name: str | None = None) -> str:
    """Return the canonical, case-insensitive identity key for an Author."""
    last = " ".join(last_name.split()).casefold()
    first = " ".join(first_name.split()).casefold() if first_name else ""
    return f"{last}\x1f{first}"


def normalize_tag_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def _tag_name_default(context: _AuthorDefaultContext) -> str:
    return normalize_tag_name(str(context.get_current_parameters().get("name") or ""))


class _AuthorDefaultContext(Protocol):
    def get_current_parameters(self) -> dict[str, Any]: ...


def _author_identity_default(context: _AuthorDefaultContext) -> str:
    parameters = context.get_current_parameters()
    first_name = parameters.get("first_name")
    return normalize_author_identity(
        str(parameters.get("last_name") or ""),
        first_name if isinstance(first_name, str) else None,
    )


def now() -> datetime:
    return datetime.now(UTC)


class SystemRole(StrEnum):
    administrator = "administrator"
    member = "member"


class WorkspaceRole(StrEnum):
    owner = "owner"
    admin = "admin"
    editor = "editor"
    reviewer = "reviewer"
    viewer = "viewer"


class WorkspaceState(StrEnum):
    active = "active"
    archived = "archived"
    deleted = "deleted"


class WorkspaceMemberState(StrEnum):
    active = "active"
    suspended = "suspended"


class ProjectState(StrEnum):
    active = "active"
    archived = "archived"
    deleted = "deleted"


class ProjectVisibility(StrEnum):
    workspace = "workspace"
    members = "members"


class AnnotationKind(StrEnum):
    highlight = "highlight"
    underline = "underline"
    strikeout = "strikeout"
    note = "note"
    free_text = "free_text"
    ink = "ink"
    rectangle = "rectangle"
    ellipse = "ellipse"
    line = "line"
    arrow = "arrow"


class AnnotationScope(StrEnum):
    private = "private"
    project = "project"


class AnnotationObjectType(StrEnum):
    annotation = "annotation"
    reply = "reply"


class FileRevisionProcessingState(StrEnum):
    pending = "pending"
    ready = "ready"


class AttachmentRole(StrEnum):
    graphical_abstract = "graphical_abstract"


def enum_type(enum_class: type[StrEnum], name: str) -> SqlEnum:
    return SqlEnum(
        enum_class,
        name=name,
        native_enum=False,
        create_constraint=False,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32), default=SystemRole.member.value)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint("state IN ('active', 'archived', 'deleted')", name="ck_workspaces_state"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(240))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    state: Mapped[WorkspaceState] = mapped_column(
        enum_type(WorkspaceState, "workspace_state"), default=WorkspaceState.active
    )
    governance_suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    governance_suspended_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'editor', 'reviewer', 'viewer')",
            name="ck_workspace_members_role",
        ),
        CheckConstraint("state IN ('active', 'suspended')", name="ck_workspace_members_state"),
        # PostgreSQL and SQLite both support this partial uniqueness form.
        Index(
            "uq_workspace_members_current",
            "workspace_id",
            "user_id",
            unique=True,
            sqlite_where=text("terminated_at IS NULL"),
            postgresql_where=text("terminated_at IS NULL"),
        ),
        Index(
            "uq_workspace_members_current_owner",
            "workspace_id",
            unique=True,
            sqlite_where=text("terminated_at IS NULL AND role = 'owner'"),
            postgresql_where=text("terminated_at IS NULL AND role = 'owner'"),
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[WorkspaceRole] = mapped_column(
        enum_type(WorkspaceRole, "workspace_role"), default=WorkspaceRole.viewer
    )
    state: Mapped[WorkspaceMemberState] = mapped_column(
        enum_type(WorkspaceMemberState, "workspace_member_state"),
        default=WorkspaceMemberState.active,
    )
    invited_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkspaceInvitation(Base):
    __tablename__ = "workspace_invitations"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'editor', 'reviewer', 'viewer')",
            name="ck_workspace_invitations_role",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[WorkspaceRole] = mapped_column(
        enum_type(WorkspaceRole, "workspace_invitation_role")
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    invited_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    user: Mapped[User] = relationship()


class ApiToken(Base):
    __tablename__ = "api_tokens"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(120))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    __table_args__ = (UniqueConstraint("workspace_id", "id", name="uq_items_workspace_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(Text, index=True)
    abstract: Mapped[str | None] = mapped_column(Text)
    publication_date: Mapped[str | None] = mapped_column(String(32))
    publication_title: Mapped[str | None] = mapped_column(Text)
    volume: Mapped[str | None] = mapped_column(String(100))
    issue: Mapped[str | None] = mapped_column(String(100))
    pages: Mapped[str | None] = mapped_column(String(100))
    affiliation: Mapped[str | None] = mapped_column(Text)
    publisher: Mapped[str | None] = mapped_column(Text)
    place_published: Mapped[str | None] = mapped_column(String(255))
    journal_abbreviation: Mapped[str | None] = mapped_column(Text)
    doi: Mapped[str | None] = mapped_column(String(500), index=True)
    identifiers: Mapped[str | None] = mapped_column(Text)
    reference_type: Mapped[str | None] = mapped_column(String(40))
    authors: Mapped[str | None] = mapped_column(Text)
    editors: Mapped[str | None] = mapped_column(Text)
    bibtex_id: Mapped[str | None] = mapped_column(String(255), index=True)
    bibtex_type: Mapped[str | None] = mapped_column(String(40))
    urls: Mapped[str | None] = mapped_column(Text)
    keywords: Mapped[str | None] = mapped_column(Text)
    custom_fields: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    revisions: Mapped[list[FileRevision]] = relationship(
        back_populates="item", cascade="all, delete-orphan", passive_deletes=True
    )
    author_links: Mapped[list[ItemAuthor]] = relationship(
        back_populates="item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ItemAuthor.position",
    )
    identifier_links: Mapped[list[ItemIdentifier]] = relationship(
        back_populates="item", cascade="all, delete-orphan", passive_deletes=True
    )
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    updater: Mapped[User | None] = relationship(foreign_keys=[updated_by])


class Author(Base):
    __tablename__ = "authors"
    __table_args__ = (UniqueConstraint("identity_key", name="uq_authors_identity"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    first_name: Mapped[str | None] = mapped_column(String(120))
    last_name: Mapped[str] = mapped_column(String(120), index=True)
    identity_key: Mapped[str] = mapped_column(
        String(512), nullable=False, default=_author_identity_default
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ItemAuthor(Base):
    __tablename__ = "item_authors"
    __table_args__ = (UniqueConstraint("item_id", "author_id", "role", name="uq_item_author_role"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[str] = mapped_column(
        ForeignKey("authors.id", ondelete="RESTRICT"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=1)
    role: Mapped[str] = mapped_column(String(20), default="author")
    is_corresponding: Mapped[bool] = mapped_column(Boolean, default=False)
    item: Mapped[Item] = relationship(back_populates="author_links")
    author: Mapped[Author] = relationship()


class ItemIdentifier(Base):
    __tablename__ = "item_identifiers"
    __table_args__ = (
        UniqueConstraint("item_id", "provider", "value", name="uq_item_provider_value"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(40), index=True)
    value: Mapped[str] = mapped_column(String(500), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    item: Mapped[Item] = relationship(back_populates="identifier_links")


class ItemRead(Base):
    __tablename__ = "item_reads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "item_id"],
            ["items.workspace_id", "items.id"],
            name="fk_item_reads_item_workspace",
            ondelete="CASCADE",
        ),
    )
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    item_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("state IN ('active', 'archived', 'deleted')", name="ck_projects_state"),
        CheckConstraint("visibility IN ('workspace', 'members')", name="ck_projects_visibility"),
        UniqueConstraint("workspace_id", "id", name="uq_projects_workspace_id"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    state: Mapped[ProjectState] = mapped_column(
        enum_type(ProjectState, "project_state"), default=ProjectState.active
    )
    visibility: Mapped[ProjectVisibility] = mapped_column(
        enum_type(ProjectVisibility, "project_visibility"), default=ProjectVisibility.workspace
    )


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "project_id", "user_id", name="uq_project_member_workspace"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_members_project_workspace",
            ondelete="CASCADE",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ProjectItem(Base):
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "project_id", "item_id", name="uq_project_items_workspace"
        ),
        UniqueConstraint("workspace_id", "id", name="uq_project_items_workspace_id"),
        UniqueConstraint(
            "workspace_id", "id", "item_id", name="uq_project_items_workspace_id_item"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_project_items_project_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "item_id"],
            ["items.workspace_id", "items.id"],
            name="fk_project_items_item_workspace",
            ondelete="CASCADE",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    __tablename__ = "project_items"
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    item_id: Mapped[str] = mapped_column(String(36), index=True)
    added_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    __table_args__ = (
        UniqueConstraint("workspace_id", "normalized_name", name="uq_tags_workspace_normalized"),
        UniqueConstraint("workspace_id", "id", name="uq_tags_workspace_id"),
    )
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), index=True)
    normalized_name: Mapped[str] = mapped_column(String(120), index=True, default=_tag_name_default)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class ItemTag(Base):
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "item_id"],
            ["items.workspace_id", "items.id"],
            name="fk_item_tags_item_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "tag_id"],
            ["tags.workspace_id", "tags.id"],
            name="fk_item_tags_tag_workspace",
            ondelete="CASCADE",
        ),
    )
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    __tablename__ = "item_tags"
    item_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tag_id: Mapped[str] = mapped_column(String(36), primary_key=True)


class ItemTagRecommendation(Base):
    __tablename__ = "item_tag_recommendations"
    __table_args__ = (
        CheckConstraint("generation_token >= 1", name="ck_item_tag_recommendations_token"),
        ForeignKeyConstraint(
            ["workspace_id", "item_id"],
            ["items.workspace_id", "items.id"],
            name="fk_item_tag_recommendations_item_workspace",
            ondelete="CASCADE",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    item_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    generation_token: Mapped[int] = mapped_column(Integer, default=1)
    workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    single_words: Mapped[str | None] = mapped_column(Text, nullable=True)
    phrases: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class DiscussionMessage(Base):
    __tablename__ = "discussion_messages"
    __table_args__ = (
        CheckConstraint(
            "(item_id IS NOT NULL AND project_id IS NULL) OR "
            "(item_id IS NULL AND project_id IS NOT NULL)",
            name="ck_discussion_messages_context",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "item_id"],
            ["items.workspace_id", "items.id"],
            name="fk_discussion_messages_item_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name="fk_discussion_messages_project_workspace",
            ondelete="CASCADE",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    item_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    author: Mapped[User] = relationship()


class FileRevision(Base):
    __tablename__ = "file_revisions"
    __table_args__ = (
        CheckConstraint(
            "processing_state IN ('pending', 'ready')",
            name="ck_file_revisions_processing_state",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_file_revisions_workspace_id"),
        UniqueConstraint(
            "workspace_id", "id", "item_id", name="uq_file_revisions_workspace_id_item"
        ),
        ForeignKeyConstraint(
            ["workspace_id", "item_id"],
            ["items.workspace_id", "items.id"],
            name="fk_file_revisions_item_workspace",
            ondelete="CASCADE",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    item_id: Mapped[str] = mapped_column(String(36), index=True)
    object_key: Mapped[str] = mapped_column(String(200), index=True)
    thumbnail_object_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    thumbnail_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    size: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/pdf")
    original_name: Mapped[str] = mapped_column(String(255))
    page_count: Mapped[int | None] = mapped_column(Integer)
    page_geometry: Mapped[str | None] = mapped_column(Text)
    full_text: Mapped[str | None] = mapped_column(Text)
    processing_state: Mapped[FileRevisionProcessingState] = mapped_column(
        enum_type(FileRevisionProcessingState, "file_revision_processing_state"),
        default=FileRevisionProcessingState.pending,
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    item: Mapped[Item] = relationship(
        back_populates="revisions",
        primaryjoin="and_(FileRevision.workspace_id == Item.workspace_id, FileRevision.item_id == Item.id)",
        foreign_keys="[FileRevision.workspace_id, FileRevision.item_id]",
    )


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        CheckConstraint(
            "role IS NULL OR role = 'graphical_abstract'",
            name="ck_attachments_role",
        ),
        UniqueConstraint("item_id", "role", name="uq_attachments_item_role"),
        ForeignKeyConstraint(
            ["workspace_id", "item_id"],
            ["items.workspace_id", "items.id"],
            name="fk_attachments_item_workspace",
            ondelete="CASCADE",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    item_id: Mapped[str] = mapped_column(String(36), index=True)
    object_key: Mapped[str] = mapped_column(String(200), index=True)
    size: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(100), default="application/octet-stream")
    original_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[AttachmentRole | None] = mapped_column(
        enum_type(AttachmentRole, "attachment_role"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class PdfAnnotationObject(Base):
    __tablename__ = "pdf_annotation_objects"
    __table_args__ = (
        CheckConstraint(
            "object_type IN ('annotation', 'reply')",
            name="ck_pdf_annotation_objects_type",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    object_type: Mapped[AnnotationObjectType] = mapped_column(
        enum_type(AnnotationObjectType, "annotation_object_type")
    )


class PdfAnnotation(Base):
    __tablename__ = "pdf_annotations"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('highlight', 'underline', 'strikeout', 'note', 'free_text', "
            "'ink', 'rectangle', 'ellipse', 'line', 'arrow')",
            name="ck_pdf_annotations_kind",
        ),
        CheckConstraint("scope IN ('private', 'project')", name="ck_pdf_annotations_scope"),
        CheckConstraint(
            "(scope = 'private' AND project_item_id IS NULL) OR "
            "(scope = 'project' AND project_item_id IS NOT NULL)",
            name="ck_pdf_annotations_project_scope",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_pdf_annotations_workspace_id"),
        ForeignKeyConstraint(
            ["workspace_id", "file_revision_id", "item_id"],
            ["file_revisions.workspace_id", "file_revisions.id", "file_revisions.item_id"],
            name="fk_pdf_annotations_revision_item_workspace",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "project_item_id", "item_id"],
            ["project_items.workspace_id", "project_items.id", "project_items.item_id"],
            name="fk_pdf_annotations_project_item_revision_item",
            ondelete="CASCADE",
        ),
    )
    id: Mapped[str] = mapped_column(
        ForeignKey(
            "pdf_annotation_objects.id",
            name="fk_pdf_annotations_object_id",
        ),
        primary_key=True,
        default=uid,
    )
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    object_identity: Mapped[PdfAnnotationObject] = relationship()
    file_revision_id: Mapped[str] = mapped_column(String(36), index=True)
    item_id: Mapped[str] = mapped_column(String(36), index=True)
    page_index: Mapped[int] = mapped_column(Integer)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[AnnotationKind] = mapped_column(enum_type(AnnotationKind, "annotation_kind"))
    scope: Mapped[AnnotationScope] = mapped_column(
        enum_type(AnnotationScope, "annotation_scope"), default=AnnotationScope.private
    )
    project_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    body: Mapped[str | None] = mapped_column(Text)
    selected_text: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    moderated_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __init__(self, **kwargs):
        object_id = kwargs.setdefault("id", uid())
        kwargs.setdefault(
            "object_identity",
            PdfAnnotationObject(
                id=object_id,
                object_type=AnnotationObjectType.annotation,
            ),
        )
        super().__init__(**kwargs)


class PdfAnnotationReply(Base):
    __tablename__ = "pdf_annotation_replies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "annotation_id"],
            ["pdf_annotations.workspace_id", "pdf_annotations.id"],
            name="fk_pdf_annotation_replies_annotation_workspace",
            ondelete="CASCADE",
        ),
    )
    id: Mapped[str] = mapped_column(
        ForeignKey(
            "pdf_annotation_objects.id",
            name="fk_pdf_annotation_replies_object_id",
        ),
        primary_key=True,
        default=uid,
    )
    workspace_id: Mapped[str] = mapped_column(String(36), index=True)
    object_identity: Mapped[PdfAnnotationObject] = relationship()
    annotation_id: Mapped[str] = mapped_column(String(36), index=True)
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __init__(self, **kwargs):
        object_id = kwargs.setdefault("id", uid())
        kwargs.setdefault(
            "object_identity",
            PdfAnnotationObject(
                id=object_id,
                object_type=AnnotationObjectType.reply,
            ),
        )
        super().__init__(**kwargs)


class ExportArtifact(Base):
    __tablename__ = "export_artifacts"
    workflow_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    object_key: Mapped[str] = mapped_column(String(500), unique=True)
    filename: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'ready', 'failed', 'committed')",
            name="ck_import_batches_status",
        ),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    file_format: Mapped[str] = mapped_column(String(16))
    records: Mapped[str] = mapped_column(Text)
    errors: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="ready")
    workflow_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    committed_item_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class CitationStyle(Base):
    __tablename__ = "citation_styles"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_citation_styles_workspace_name"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    workspace_id: Mapped[str] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120))
    csl_xml: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    workspace_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    project_id: Mapped[str | None] = mapped_column(
        ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str] = mapped_column(String(80))
    target_id: Mapped[str | None] = mapped_column(String(36))
    detail: Mapped[str | None] = mapped_column(Text)
    target_ids: Mapped[str | None] = mapped_column(Text)
    authorization_role: Mapped[str | None] = mapped_column(String(32))
    authorization_capability: Mapped[str | None] = mapped_column(String(80))
    result: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SystemSetting(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    updated_by: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ObjectIntegrityScan(Base):
    __tablename__ = "object_integrity_scans"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    status: Mapped[str] = mapped_column(String(32))
    missing_count: Mapped[int] = mapped_column(Integer, default=0)
    mismatch_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str] = mapped_column(Text, default="[]")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
