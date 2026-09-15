from __future__ import annotations

import pytest

from quirebase.core.database import async_database_url


def test_async_database_url_selects_the_psycopg_driver_for_libpq_urls():
    assert (
        async_database_url("postgres://user:pw@host/db") == "postgresql+psycopg://user:pw@host/db"
    )
    assert (
        async_database_url("postgresql://user:pw@host/db") == "postgresql+psycopg://user:pw@host/db"
    )
    assert async_database_url("sqlite:///./quirebase.db") == "sqlite+aiosqlite:///./quirebase.db"
    assert (
        async_database_url("sqlite+aiosqlite:///./quirebase.db")
        == "sqlite+aiosqlite:///./quirebase.db"
    )


def test_driver_suffixed_postgresql_urls_are_configuration_errors():
    for url in (
        "postgresql+asyncpg://user:pw@host/db",
        "postgresql+psycopg2://user:pw@host/db",
        "postgresql+psycopg://user:pw@host/db",
    ):
        with pytest.raises(ValueError, match="unsupported database URL scheme"):
            async_database_url(url)


def test_url_normalization_preserves_percent_encoding():
    encoded = "postgresql://user:p%20ss@host/db?options=-c%20search_path%3Dprivate"
    assert (
        async_database_url(encoded)
        == "postgresql+psycopg://user:p%20ss@host/db?options=-c%20search_path%3Dprivate"
    )
