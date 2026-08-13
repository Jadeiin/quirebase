import json

import httpx
import pytest
from sqlalchemy import select
from test_http import authenticated_client

from quirebase.app import app
from quirebase.config import Settings, get_settings
from quirebase.metadata_lookup import (
    Identifier,
    MetadataLookupError,
    lookup_metadata,
    parse_identifier,
)
from quirebase.models import AuditEvent, ImportBatch, Item


def response(request: httpx.Request) -> httpx.Response:
    if request.url.host == "api.crossref.org":
        if "10.9999" in str(request.url):
            return httpx.Response(404)
        assert "/10.1234%2Fsample" in str(request.url)
        return httpx.Response(
            200,
            json={
                "message": {
                    "title": ["DOI Example"],
                    "abstract": "<jats:p>An abstract</jats:p>",
                    "author": [{"family": "Doe", "given": "Jane"}],
                    "container-title": ["Journal"],
                    "published-online": {"date-parts": [[2025, 2, 3]]},
                    "DOI": "10.1234/sample",
                    "type": "journal-article",
                }
            },
        )
    if request.url.host == "eutils.ncbi.nlm.nih.gov":
        return httpx.Response(
            200,
            json={
                "result": {
                    "42": {
                        "title": "PubMed Example",
                        "authors": [{"name": "Doe J"}],
                        "fulljournalname": "Medical Journal",
                        "pubdate": "2024",
                        "articleids": [{"idtype": "doi", "value": "10.2/pubmed"}],
                    }
                }
            },
        )
    if request.url.host == "api.datacite.org":
        return httpx.Response(
            200,
            json={
                "data": {
                    "attributes": {
                        "doi": "10.9999/dataset",
                        "titles": [{"title": "DataCite Example"}],
                        "creators": [{"name": "Example, Ada"}],
                        "publisher": "Repository",
                        "publicationYear": 2026,
                        "types": {"resourceTypeGeneral": "Dataset"},
                    }
                }
            },
        )
    if request.url.host == "api.openalex.org":
        assert request.url.path == "/works/W123"
        return httpx.Response(
            200,
            json={
                "id": "https://openalex.org/W123",
                "display_name": "OpenAlex Example",
                "doi": "https://doi.org/10.4/openalex",
                "publication_date": "2026-01-01",
                "type": "article",
                "authorships": [{"author": {"display_name": "Alex Author"}}],
                "primary_location": {"source": {"display_name": "Open Journal"}},
                "topics": [{"display_name": "Open science"}],
            },
        )
    if request.url.host == "openlibrary.org":
        return httpx.Response(
            200,
            json={
                "ISBN:9780131103627": {
                    "title": "The C Programming Language",
                    "authors": [{"name": "Brian Kernighan"}],
                    "publishers": [{"name": "Prentice Hall"}],
                    "publish_date": "1988",
                }
            },
        )
    assert request.url.host == "export.arxiv.org"
    return httpx.Response(
        200,
        text="""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
          <entry><title>arXiv Example</title><summary>Preprint abstract</summary>
          <published>2023-01-02T00:00:00Z</published><author><name>Ada Example</name></author>
          <category term="cs.CL"/><arxiv:doi>10.3/arxiv</arxiv:doi></entry>
        </feed>""",
    )


@pytest.mark.parametrize(
    ("value", "provider", "expected"),
    [
        ("https://doi.org/10.1234/sample", "auto", Identifier("doi", "10.1234/sample")),
        ("PMID: 42", "auto", Identifier("pmid", "42")),
        ("arXiv:1706.03762v7", "auto", Identifier("arxiv", "1706.03762v7")),
        ("ISBN 978-0-13-110362-7", "auto", Identifier("isbn", "9780131103627")),
        ("https://openalex.org/W123", "auto", Identifier("openalex", "W123")),
    ],
)
def test_identifier_detection(value, provider, expected):
    assert parse_identifier(value, provider) == expected


def test_identifier_input_cannot_be_used_as_an_arbitrary_url():
    with pytest.raises(ValueError):
        parse_identifier("https://127.0.0.1/admin", "auto")


@pytest.mark.parametrize(
    ("value", "provider", "title"),
    [
        ("10.1234/sample", "doi", "DOI Example"),
        ("42", "pmid", "PubMed Example"),
        ("1706.03762", "arxiv", "arXiv Example"),
        ("10.9999/dataset", "doi", "DataCite Example"),
        ("9780131103627", "isbn", "The C Programming Language"),
        ("W123", "openalex", "OpenAlex Example"),
    ],
)
def test_provider_adapters_map_records(value, provider, title):
    parsed, record = lookup_metadata(
        value,
        provider,
        settings=Settings(metadata_contact_email="operator@example.org"),
        transport=httpx.MockTransport(response),
    )
    assert parsed.provider == provider
    assert record["title"] == title
    assert json.loads(record["identifiers"])


def test_metadata_response_size_is_limited():
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, content=b"x" * 2048))
    with pytest.raises(MetadataLookupError, match="size limit"):
        lookup_metadata(
            "10.1234/sample",
            "doi",
            settings=Settings(metadata_max_response_bytes=1024),
            transport=transport,
        )


def test_online_preview_uses_existing_confirmed_import_flow(db, tmp_path, monkeypatch):
    client, _item, _revision = authenticated_client(db, tmp_path, monkeypatch)
    record = {
        "title": "Looked-up paper",
        "abstract": "Remote metadata",
        "authors": "Doe, Jane",
        "keywords": None,
        "publication_date": "2026",
        "publication_title": "Journal",
        "doi": "10.1/looked-up",
        "identifiers": json.dumps({"doi": "10.1/looked-up"}),
        "reference_type": "journal-article",
    }
    monkeypatch.setattr(
        "quirebase.app.lookup_metadata",
        lambda _value, _provider: (Identifier("doi", "10.1/looked-up"), record),
    )
    try:
        preview = client.post(
            "/metadata/preview?csrf_token=test-csrf",
            data={"identifier": "10.1/looked-up", "provider": "auto"},
        )
        assert preview.status_code == 200
        assert "Looked-up paper" in preview.text
        assert db.scalar(select(Item).where(Item.title == "Looked-up paper")) is None
        batch = db.scalar(select(ImportBatch).where(ImportBatch.file_format == "metadata:doi"))
        committed = client.post(
            f"/bibliography/import/{batch.id}?csrf_token=test-csrf", follow_redirects=False
        )
        assert committed.status_code == 303
        imported = db.scalar(select(Item).where(Item.title == "Looked-up paper"))
        assert imported.doi == "10.1/looked-up"
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "metadata.lookup"))
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
