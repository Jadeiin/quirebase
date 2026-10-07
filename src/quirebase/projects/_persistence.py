"""Project persistence; participation and authorization stay in commands."""

from quirebase.core.persistence import Repository, Service
from quirebase.models import Project, ProjectParticipant


class ProjectRepository(Repository[Project]):
    model_type = Project


class ProjectService(Service[Project]):
    repository_type = ProjectRepository


class ProjectParticipantRepository(Repository[ProjectParticipant]):
    model_type = ProjectParticipant
