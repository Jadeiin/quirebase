"""Account persistence on the existing account transaction."""

from quirebase.core.persistence import Repository, Service
from quirebase.models import Invitation, User


class UserRepository(Repository[User]):
    model_type = User


class UserService(Service[User]):
    repository_type = UserRepository


class InvitationRepository(Repository[Invitation]):
    model_type = Invitation
