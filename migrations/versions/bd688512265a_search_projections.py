"""search projections

Revision ID: bd688512265a
Revises: e74ae5ea11b2
Create Date: 2026-10-09 20:08:04.445451

"""

import warnings
from typing import TYPE_CHECKING

import sqlalchemy as sa
from alembic import op
from advanced_alchemy.types import Bool, EncryptedString, EncryptedText, GUID, JsonB, ORA_JSONB, DateTimeUTC, StoredObject, PasswordHash, FernetBackend, TOTPSecret, OneTimeCode
from advanced_alchemy.types.encrypted_string import PGCryptoBackend
from advanced_alchemy.types.password_hash.argon2 import Argon2Hasher
from advanced_alchemy.types.password_hash.passlib import PasslibHasher
from advanced_alchemy.types.password_hash.pwdlib import PwdlibHasher
from sqlalchemy import Text  # noqa: F401


if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ("downgrade", "upgrade", "schema_upgrades", "schema_downgrades", "data_upgrades", "data_downgrades")

sa.GUID = GUID
sa.Bool = Bool
sa.DateTimeUTC = DateTimeUTC
sa.JsonB = JsonB
sa.ORA_JSONB = ORA_JSONB
sa.EncryptedString = EncryptedString
sa.EncryptedText = EncryptedText
sa.StoredObject = StoredObject
sa.PasswordHash = PasswordHash
sa.Argon2Hasher = Argon2Hasher
sa.PasslibHasher = PasslibHasher
sa.PwdlibHasher = PwdlibHasher
sa.FernetBackend = FernetBackend
sa.PGCryptoBackend = PGCryptoBackend
sa.TOTPSecret = TOTPSecret
sa.OneTimeCode = OneTimeCode

# revision identifiers, used by Alembic.
revision = 'bd688512265a'
down_revision = 'e74ae5ea11b2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        with op.get_context().autocommit_block():
            schema_upgrades()
            data_upgrades()

def downgrade() -> None:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=UserWarning)
        with op.get_context().autocommit_block():
            data_downgrades()
            schema_downgrades()

def schema_upgrades() -> None:
    """schema upgrade migrations go here."""
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE TABLE item_search (
                item_id uuid PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
                document tsvector NOT NULL
            )
            """
        )
        op.execute("CREATE INDEX ix_item_search_document ON item_search USING gin(document)")
        op.execute(
            """
            CREATE TABLE revision_search (
                revision_id uuid PRIMARY KEY REFERENCES file_revisions(id) ON DELETE CASCADE,
                item_id uuid NOT NULL,
                document tsvector NOT NULL
            )
            """
        )
        op.execute(
            "CREATE INDEX ix_revision_search_document ON revision_search USING gin(document)"
        )
        op.execute("CREATE INDEX ix_revision_search_item_id ON revision_search(item_id)")
    else:
        op.execute(
            """
            CREATE VIRTUAL TABLE item_search USING fts5(
                item_id UNINDEXED,
                content,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )
        op.execute(
            """
            CREATE VIRTUAL TABLE revision_search USING fts5(
                revision_id UNINDEXED,
                item_id UNINDEXED,
                content,
                tokenize='unicode61 remove_diacritics 2'
            )
            """
        )

def schema_downgrades() -> None:
    """schema downgrade migrations go here."""
    op.execute("DROP TABLE IF EXISTS revision_search")
    op.execute("DROP TABLE IF EXISTS item_search")

def data_upgrades() -> None:
    """Add any optional data upgrade migrations here!"""

def data_downgrades() -> None:
    """Add any optional data downgrade migrations here!"""
