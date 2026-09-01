from __future__ import annotations

import asyncio
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must contain at least 12 characters")
    return password_hasher.hash(password)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


async def hash_password_async(password: str) -> str:
    """Hash a password without running Argon2 on the event-loop thread."""
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(encoded: str, password: str) -> bool:
    """Verify a password without running Argon2 on the event-loop thread."""
    return await asyncio.to_thread(verify_password, encoded, password)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def generate_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def compare_digest(a: str, b: str) -> bool:
    return secrets.compare_digest(a, b)


def compare_digest_bytes(a: bytes, b: bytes) -> bool:
    return secrets.compare_digest(a, b)
