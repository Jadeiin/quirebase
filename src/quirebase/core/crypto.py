from __future__ import annotations

import asyncio
import hashlib
import secrets

from advanced_alchemy.types import HashedPassword

from quirebase.core.passwords import password_backend


def hash_password(password: str) -> HashedPassword:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    return HashedPassword(password_backend.hash(password), password_backend)


def verify_password(encoded: HashedPassword, password: str) -> bool:
    return encoded.verify(password)


async def hash_password_async(password: str) -> HashedPassword:
    """Hash a password without running Argon2 on the event-loop thread."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(encoded: HashedPassword, password: str) -> bool:
    """Verify a password without running Argon2 on the event-loop thread."""
    return await asyncio.to_thread(verify_password, encoded, password)


async def verify_and_update_password(
    encoded: HashedPassword, password: str
) -> tuple[bool, HashedPassword | None]:
    valid, upgraded = await asyncio.to_thread(encoded.verify_and_update, password)
    return valid, HashedPassword(upgraded, password_backend) if upgraded else None


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def compare_digest(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)


def compare_digest_bytes(a: bytes, b: bytes) -> bool:
    return secrets.compare_digest(a, b)
