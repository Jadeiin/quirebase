"""Argon2 values prepared off the event loop before entering ORM persistence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from advanced_alchemy.types import HashedPassword, PasswordHash
from advanced_alchemy.types.password_hash.argon2 import Argon2Hasher
from sqlalchemy import Text

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect

password_backend = Argon2Hasher()


class PreparedPasswordHash(PasswordHash):
    """Keep AA's password value and rehash API without hashing twice on flush."""

    cache_ok = True
    impl: Any = Text

    def __init__(self) -> None:
        super().__init__(backend=password_backend)
        self.impl = Text()

    def process_bind_param(self, value: Any, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            # Strings here are already encoded hashes, including SQL CAS comparisons.
            # Business password inputs are always prepared with hash_password_async.
            return value
        if not isinstance(value, HashedPassword):
            raise TypeError("prepare passwords off the event loop before persistence")
        return value.hash_string
