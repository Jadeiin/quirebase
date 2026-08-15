from __future__ import annotations


class DomainError(Exception):
    pass


class ResourceNotFound(DomainError):
    pass


class ResourceUnavailable(DomainError):
    """The caller must not learn whether the resource exists."""


class PermissionDenied(DomainError):
    pass


class ValidationFailure(DomainError):
    pass


class SizeLimitExceeded(DomainError):
    pass


class VersionConflict(DomainError):
    def __init__(self, current_version: int | None = None, message: str | None = None):
        msg = message or f"version conflict, current version is {current_version}"
        super().__init__(msg)
        self.current_version = current_version
