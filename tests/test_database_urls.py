from __future__ import annotations

import pytest

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


def test_async_database_url_translates_asyncpg_ssl_option():
    assert (
        async_database_url("postgresql+asyncpg://user:pw@host/db?ssl=require")
        == "postgresql+psycopg://user:pw@host/db?sslmode=require"
    )
    assert (
        async_database_url("postgresql+asyncpg://user:pw@host/db?ssl=verify-full")
        == "postgresql+psycopg://user:pw@host/db?sslmode=verify-full"
    )
    assert (
        async_database_url("postgresql+asyncpg://user:pw@host/db?ssl=true")
        == "postgresql+psycopg://user:pw@host/db?sslmode=require"
    )
    assert (
        async_database_url("postgresql+asyncpg://user:pw@host/db?ssl=0")
        == "postgresql+psycopg://user:pw@host/db?sslmode=disable"
    )


def test_async_database_url_preserves_libpq_options_and_encoded_passwords():
    assert (
        async_database_url("postgresql+asyncpg://user:p%40ss@host/db?application_name=quirebase")
        == "postgresql+psycopg://user:p%40ss@host/db?application_name=quirebase"
    )
    assert (
        async_database_url("postgresql+asyncpg://user:pw@host/db?application_name=qb&ssl=require")
        == "postgresql+psycopg://user:pw@host/db?application_name=qb&sslmode=require"
    )


def test_async_database_url_rejects_asyncpg_only_options():
    with pytest.raises(ValueError, match="statement_cache_size"):
        async_database_url("postgresql+asyncpg://user:pw@host/db?statement_cache_size=0")
    with pytest.raises(ValueError, match="server_settings"):
        async_database_url("postgresql://user:pw@host/db?server_settings=timezone%3DUTC")
    with pytest.raises(ValueError, match="unsupported asyncpg ssl option"):
        async_database_url("postgresql+asyncpg://user:pw@host/db?ssl=maybe")


def test_libpq_database_url_translates_asyncpg_options():
    assert (
        libpq_database_url("postgresql+asyncpg://user:pw@host/db?ssl=require")
        == "postgresql://user:pw@host/db?sslmode=require"
    )
    assert (
        libpq_database_url("postgres://user:pw@host/db?ssl=require")
        == "postgresql://user:pw@host/db?sslmode=require"
    )
    assert (
        libpq_database_url("postgresql://user:pw@host/db?ssl=true")
        == "postgresql://user:pw@host/db?sslmode=require"
    )
    with pytest.raises(ValueError, match="command_timeout"):
        libpq_database_url("postgresql+psycopg://user:pw@host/db?command_timeout=5")
