from quirebase.core.database import async_database_url, libpq_database_url


def test_async_database_url_normalizes_postgresql_driver_spellings():
    assert (
        async_database_url("postgres://user:pw@host/db") == "postgresql+psycopg://user:pw@host/db"
    )
    assert (
        async_database_url("postgresql://user:pw@host/db") == "postgresql+psycopg://user:pw@host/db"
    )
    assert (
        async_database_url("postgresql+psycopg2://user:pw@host/db")
        == "postgresql+psycopg://user:pw@host/db"
    )
    assert (
        async_database_url("postgresql+asyncpg://user:pw@host/db")
        == "postgresql+psycopg://user:pw@host/db"
    )
    assert (
        async_database_url("postgresql+psycopg://user:pw@host/db")
        == "postgresql+psycopg://user:pw@host/db"
    )
    assert async_database_url("sqlite:///./quirebase.db") == "sqlite+aiosqlite:///./quirebase.db"
    assert (
        async_database_url("sqlite+aiosqlite:///./quirebase.db")
        == "sqlite+aiosqlite:///./quirebase.db"
    )


def test_libpq_database_url_strips_sqlalchemy_driver_suffixes():
    assert (
        libpq_database_url("postgresql+psycopg://user:pw@host:5432/db")
        == "postgresql://user:pw@host:5432/db"
    )
    assert libpq_database_url("postgresql+psycopg2://user@host/db") == "postgresql://user@host/db"
    assert libpq_database_url("postgresql+asyncpg://user@host/db") == "postgresql://user@host/db"
    assert libpq_database_url("postgresql://user@host/db") == "postgresql://user@host/db"
    assert libpq_database_url("sqlite:///./quirebase.db") == "sqlite:///./quirebase.db"
