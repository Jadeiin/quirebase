from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from quirebase.core.errors import PermissionDenied, ResourceUnavailable
from quirebase.models import Project, ProjectMember, ProjectRole, SystemRole, User

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def visible_projects(db: Session, user: User) -> list[Project]:
    query = select(Project).order_by(Project.name)
    if user.role != SystemRole.administrator.value:
        query = query.join(ProjectMember).where(ProjectMember.user_id == user.id)
    return list(db.scalars(query).all())


def editable_projects(db: Session, user: User) -> list[Project]:
    return list(
        db.scalars(
            select(Project)
            .join(ProjectMember)
            .where(
                ProjectMember.user_id == user.id,
                ProjectMember.role.in_([ProjectRole.owner, ProjectRole.editor]),
            )
            .order_by(Project.name)
        ).all()
    )


def project_member(db: Session, user: User, project_id: str | None) -> ProjectMember | None:
    if project_id is None:
        return None
    return db.get(ProjectMember, (project_id, user.id))


def require_project_member(
    db: Session, user: User, project_id: str, allowed_roles: set[str] | None = None
) -> ProjectMember:
    member = project_member(db, user, project_id)
    if member is None:
        if user.role == SystemRole.administrator.value:
            project = db.get(Project, project_id)
            if project is None:
                raise ResourceUnavailable("project not found")
            return ProjectMember(
                project_id=project_id, user_id=user.id, role=SystemRole.administrator.value
            )
        raise ResourceUnavailable("project not found or membership required")
    if allowed_roles and member.role not in allowed_roles:
        raise PermissionDenied("insufficient project role permissions")
    return member
