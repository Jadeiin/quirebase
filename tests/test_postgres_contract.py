import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from quirebase.db import Base
from quirebase.models import Item, User
from quirebase.search import search_index


@pytest.mark.skipif(
    not os.getenv("QUIREBASE_TEST_POSTGRES_URL"), reason="PostgreSQL is not configured"
)
def test_postgresql_search_contract():
    engine = create_engine(os.environ["QUIREBASE_TEST_POSTGRES_URL"])
    Base.metadata.create_all(engine)
    username = f"contract-{uuid.uuid4()}"
    try:
        with Session(engine) as db:
            user = User(username=username, password_hash="unused")
            db.add(user)
            db.flush()
            item = Item(
                title="Spectral graph methods", abstract="Topological signal", created_by=user.id
            )
            db.add(item)
            db.flush()
            search_index(db).index_item(db, item.id)
            assert search_index(db).search(db, "topological") == [item.id]
            db.rollback()
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS item_search"))
        Base.metadata.drop_all(engine)
        engine.dispose()
