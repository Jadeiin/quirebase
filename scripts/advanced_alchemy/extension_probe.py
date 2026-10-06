"""Research AA extension behavior against real Quirebase mappings on scratch SQLite.

uv run --frozen python scripts/advanced_alchemy/extension_probe.py
This probes adoption boundaries; it does not modify application models or migrations.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

HERE = Path(__file__).parent


async def run(scratch: Path) -> dict:
    from advanced_alchemy.config import AsyncSessionConfig, EngineConfig, SQLAlchemyAsyncConfig
    from advanced_alchemy.filters import LimitOffset
    from advanced_alchemy.mixins import UniqueMixin
    from advanced_alchemy.repository import SQLAlchemyAsyncRepository
    from advanced_alchemy.service import ResultConverter
    from advanced_alchemy.types import EncryptedString, FileObject, JsonB, MutableList
    from advanced_alchemy.utils.serialization import decode_json, encode_json
    from fastapi.encoders import jsonable_encoder
    from sqlalchemy import (
        Column,
        Integer,
        MetaData,
        String,
        Table,
        func,
        inspect,
        literal,
        select,
        text,
        update,
    )
    from sqlalchemy.exc import IntegrityError, StatementError
    from sqlalchemy.orm import DeclarativeBase
    from uuid_utils.compat import uuid7

    from quirebase.core.database import Base, async_database_url, make_async_engine
    from quirebase.core.storage import ObjectSuffix, get_object_store
    from quirebase.library.authors import find_or_create_author
    from quirebase.models import Attachment, Author, Item, User, normalize_author_identity
    from quirebase.web.api.admin_schemas import AdminUserView
    from quirebase.workspaces import provision_initial_workspace

    config = SQLAlchemyAsyncConfig(
        connection_string=async_database_url(f"sqlite:///{scratch / 'research.db'}"),
        engine_config=EngineConfig(pool_pre_ping=True),
        session_config=AsyncSessionConfig(expire_on_commit=False),
        metadata=Base.metadata,
        enable_file_object_listener=False,
        enable_touch_updated_timestamp_listener=False,
    )
    engine = config.get_engine()
    sessions = config.create_session_maker()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    evidence = {"advanced_alchemy": "1.11.0", "postgres_runtime": False}
    try:
        payload = {"actor_id": uuid7(), "results": [{"id": uuid7()}]}
        current = make_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with current.connect() as connection:
                try:
                    await connection.scalar(select(literal(payload, type_=JsonB)))
                except StatementError as error:
                    evidence["json"] = {"existing_engine_uuid_failure": type(error.orig).__name__}
                else:
                    raise AssertionError("Expected standard JSON serialization to reject UUID")
        finally:
            await current.dispose()
        async with engine.connect() as connection:
            value = await connection.scalar(select(literal(payload, type_=JsonB)))
            assert value == decode_json(encode_json(payload))
            evidence["json"].update({
                "aa_engine_config_uuid_roundtrip": True,
                "uuid_inside_json_returns_string": isinstance(value["actor_id"], str),
                "sqlite_type": str(JsonB.compile(dialect=engine.dialect)),
            })
        try:
            entries = MutableList([{"row": 1}])
            entries[0] = {"row": 2}
        except TypeError as error:
            evidence["mutable_list"] = {"dict_replacement_error": str(error)}
        else:
            raise AssertionError("Expected hash-based removed tracking to reject dict entries")

        async with sessions() as db:
            actor = User(username="research-admin", password_hash="unused", role="administrator")
            db.add(actor)
            await db.flush()
            workspace = await provision_initial_workspace(db, actor)
            item = Item(
                workspace_id=workspace.id, title="Research actual document", created_by=actor.id
            )
            db.add(item)
            await db.flush()
            store = get_object_store()
            stored = await store.put_object(
                uuid4(), ObjectSuffix.BINARY, b"research", max_bytes=100
            )
            attachment = Attachment(
                workspace_id=workspace.id,
                item_id=item.id,
                created_by=actor.id,
                file=FileObject(
                    backend="documents",
                    filename=stored.key,
                    size=stored.size,
                    content_type="text/plain",
                    metadata={"original_name": "before.txt"},
                ),
            )
            db.add(attachment)
            await db.commit()
            actor_id, attachment_id = actor.id, attachment.id
            attachment.file.update_metadata({"original_name": "in-place.txt"})
            await db.commit()
            await db.refresh(attachment)
            assert attachment.file.metadata["original_name"] == "before.txt"
            replacement = FileObject(
                **(attachment.file.to_dict() | {"metadata": {"original_name": "replaced.txt"}})
            )
            assert replacement == attachment.file
            attachment.file = replacement
            await db.commit()
            await db.refresh(attachment)
            assert attachment.file.metadata["original_name"] == "before.txt"
            await db.execute(
                update(Attachment).where(Attachment.id == attachment_id).values(file=replacement)
            )
            await db.commit()
            await db.refresh(attachment)
            assert attachment.file.metadata["original_name"] == "replaced.txt"
            evidence["file_metadata"] = {
                "actual_attachment_mapping": True,
                "in_place_change_persists_without_listener": False,
                "same_path_replacement_persists": False,
                "file_equality_ignores_metadata": True,
                "explicit_sql_update_persists": True,
            }
            user_view = ResultConverter().to_schema(
                [actor],
                schema_type=AdminUserView,
                total=1,
                filters=[LimitOffset(limit=20, offset=0)],
            )
            raw_converter_json = decode_json(encode_json(user_view))
            serialized_view = encode_json(jsonable_encoder(user_view))
            assert decode_json(serialized_view)["items"][0]["id"] == str(actor_id)
            assert "password_hash" not in serialized_view
            evidence["projection"] = {
                "result_converter_existing_admin_dto": True,
                "aa_default_encode_json_pagination_type": type(raw_converter_json).__name__,
                "fastapi_jsonable_encoder_roundtrip": True,
                "schema_allowlist_excludes_password": True,
                "pagination_fields": sorted(decode_json(serialized_view)),
            }

        # Map UniqueMixin onto the actual Author table, without changing its schema.
        class AlternativeMapping(DeclarativeBase):
            pass

        class UniqueAuthor(UniqueMixin, AlternativeMapping):
            __table__ = Author.__table__

            @classmethod
            def unique_hash(cls, last_name, first_name=None):
                return normalize_author_identity(last_name, first_name)

            @classmethod
            def unique_filter(cls, last_name, first_name=None):
                return cls.identity_key == normalize_author_identity(last_name, first_name)

        async with sessions() as db:
            candidate = await UniqueAuthor.as_unique_async(db, last_name="CacheRollback")
            assert await UniqueAuthor.as_unique_async(db, last_name="CacheRollback") is candidate
            await db.flush()
            await db.rollback()
            after = await UniqueAuthor.as_unique_async(db, last_name="CacheRollback")
            assert after is candidate and inspect(after).transient
            await db.flush()
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Author)
                    .where(Author.identity_key == normalize_author_identity("CacheRollback"))
                )
                == 0
            )
        async with sessions() as first, sessions() as second:
            await UniqueAuthor.as_unique_async(first, last_name="TwoWriters")
            await UniqueAuthor.as_unique_async(second, last_name="TwoWriters")
            await first.commit()
            try:
                await second.commit()
            except IntegrityError:
                await second.rollback()
            else:
                raise AssertionError("Expected uniqueness conflict after independent reads")
        async with sessions() as db:
            author = await find_or_create_author(db, "TwoWriters")
            assert author is not None
        evidence["unique_mixin"] = {
            "actual_author_table": True,
            "session_deduplication": True,
            "rollback_returns_stale_transient_cached_object": True,
            "independent_session_creates_require_conflict_handling": True,
            "current_author_helper_resolves_committed_identity": True,
        }

        class AuthorRepository(SQLAlchemyAsyncRepository[Author]):
            model_type = Author

        async with sessions() as db:
            author = Author(last_name="UpsertTarget", first_name="Original")
            db.add(author)
            await db.commit()
            author_id = author.id
            await AuthorRepository(session=db, auto_commit=False).upsert_many(
                [
                    Author(
                        last_name="UpsertTarget",
                        first_name="ORIGINAL",
                        identity_key=author.identity_key,
                    )
                ],
                match_fields=["identity_key"],
            )
            await db.refresh(author)
            assert author.first_name == "ORIGINAL"
            await db.rollback()
        async with sessions() as db:
            assert (await db.get(Author, author_id)).first_name == "Original"
        evidence["bulk_upsert"] = {
            "actual_author_table": True,
            "matched_existing_identity_is_updated": True,
            "session_rollback_preserved": True,
            "implementation_is_read_then_add_update_not_atomic_conflict_insert": True,
        }

        # Exercise encrypted provider-setting storage with an explicit ephemeral research key.
        secret_key = os.urandom(32)
        metadata = MetaData()
        credentials = Table(
            "research_provider_credentials",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("provider", String(32)),
            Column("secret", EncryptedString(key=secret_key)),
        )
        async with engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(
                credentials.insert().values(id=1, provider="nasa", secret="research-only-token")
            )
            raw = await connection.scalar(
                text("SELECT secret FROM research_provider_credentials WHERE id=1")
            )
            assert raw != "research-only-token"
        await engine.dispose()
        credentials.c.secret.type = EncryptedString(key=secret_key)
        async with engine.connect() as connection:
            assert await connection.scalar(select(credentials.c.secret)) == "research-only-token"
        evidence["encrypted_string"] = {
            "explicit_key_ciphertext_at_rest": True,
            "engine_reopen_roundtrip": True,
            "stable_key_required_across_workers_and_restarts": True,
        }
    finally:
        await engine.dispose()
    return evidence


def main():
    scratch = Path(tempfile.mkdtemp(prefix="quirebase-aa-extension-research-"))
    os.environ.update({
        "QUIREBASE_DATABASE_URL": f"sqlite:///{scratch / 'unused-configured.db'}",
        "QUIREBASE_DATA_DIR": str(scratch / "data"),
        "FASTAPI_ENV": "development",
    })
    evidence = asyncio.run(run(scratch))
    (HERE / "extension_evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
