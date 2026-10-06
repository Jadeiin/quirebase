"""Workspace persistence on the command or request Session."""

from quirebase.core.persistence import Repository, Service
from quirebase.models import Workspace, WorkspaceMember


class WorkspaceRepository(Repository[Workspace]):
    model_type = Workspace


class WorkspaceService(Service[Workspace]):
    repository_type = WorkspaceRepository


class WorkspaceMemberRepository(Repository[WorkspaceMember]):
    model_type = WorkspaceMember
