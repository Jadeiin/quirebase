from copy import deepcopy
from uuid import uuid4

import bibtexparser
import pytest
from inquiro.work import validate_work
from sqlalchemy import select
from test_http import authenticated_async_client

from quirebase.models import AuditEvent, Item

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("endpoint", ["download", "content", "selection"])
async def test_export_preferences_apply_across_http_entry_points(
    async_db, async_session_factory, tmp_path, monkeypatch, endpoint
):
    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{seed.workspace_id}/items"
    work = {
        "id": "https://doi.org/10.1000/options",
        "type": "JournalArticle",
        "title": "<i>DNA</i> café & 50%",
        "description": "Abstract",
        "publisher": {"name": "Publisher"},
        "url": "https://example.org/article",
    }
    options = {
        "file_format": "bibtex",
        "preserve_case": True,
        "encoding": "latex",
        "doi_policy": "omit",
        "url_policy": "omit",
        "sort_by": "author",
        "excluded_fields": ["abstract", "publisher"],
    }
    try:
        created = await client.post(base, json={"metadata": work, "citation_key": "Manual"})
        assert created.status_code == 201
        item_path = f"{base}/{created.json()['id']}"
        if endpoint == "selection":
            response = await client.post(
                f"{base}/bibliography", json={"item_ids": [created.json()["id"]], **options}
            )
        else:
            suffix = "/content" if endpoint == "content" else ""
            response = await client.get(f"{item_path}/bibliography{suffix}", params=options)
        assert response.status_code == 200, response.text
        entry = bibtexparser.loads(response.text).entries[0]
        assert entry["ID"] == "Manual"
        assert entry["title"].startswith(r"{\textit{DNA}")
        assert "café" not in entry["title"] and r"\&" in entry["title"]
        assert not {"doi", "url", "abstract", "publisher"}.intersection(entry)
        assert (await client.get(item_path)).json()["metadata"] == work
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "file_format,options",
    [
        ("csl-json", {"excluded_fields": ["id"]}),
        ("ris", {"excluded_fields": ["AB"]}),
        ("bibtex", {"encoding": "invalid"}),
    ],
)
async def test_invalid_export_preferences_return_http_validation_errors(
    async_db, async_session_factory, tmp_path, monkeypatch, file_format, options
):
    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{seed.workspace_id}/items"
    try:
        created = await client.post(base, json={"metadata": metadata()})
        response = await client.post(
            f"{base}/bibliography",
            json={"item_ids": [created.json()["id"]], "file_format": file_format, **options},
        )
        assert response.status_code == 422
    finally:
        await client.aclose()


def metadata():
    return {
        "id": "https://doi.org/10.1000/shared",
        "type": "Dataset",
        "title": "Rich <i>dataset</i>",
        "contributors": [
            {
                "type": "Organization",
                "organization": {"name": "Research Council"},
                "roles": ["Author"],
            },
            {
                "type": "Person",
                "person": {
                    "family_name": "Smith",
                    "given_name": "Jane",
                    "id": "https://orcid.org/0000-0002-1825-0097",
                    "affiliations": [
                        {
                            "name": "University",
                            "identifier_type": "ROR",
                            "identifier": "https://ror.org/03yrm5c26",
                        }
                    ],
                },
                "roles": ["Editor"],
            },
        ],
        "identifiers": [{"identifier_type": "DOI", "identifier": "10.1000/other"}],
        "funding_references": [{"funder_name": "Foundation"}],
        "relations": [{"id": "https://doi.org/10.1000/related", "type": "IsSupplementTo"}],
        "files": [{"url": "https://example.test/download", "mime_type": "application/pdf"}],
        "date_published": "2026-08",
        "subjects": [{"subject": "Graph; theory"}],
    }


async def test_http_full_work_roundtrip_and_duplicate_coexistence(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{seed.workspace_id}/items"
    work = metadata()
    try:
        first = await client.post(base, json={"metadata": work, "citation_key": "ManualKey"})
        second = await client.post(base, json={"metadata": work})
        assert first.status_code == second.status_code == 201
        assert first.json()["id"] != second.json()["id"]
        path = f"{base}/{first.json()['id']}"
        read = (await client.get(path)).json()
        assert read["metadata"] == work
        validate_work(read["metadata"])
        overview = (await client.get(f"{path}/overview")).json()
        assert overview["metadata"] == work and overview["citation_key"] == "ManualKey"
        updated = deepcopy(read["metadata"]) | {"title": "Changed title"}
        response = await client.put(
            path,
            json={
                "expected_version": read["version"],
                "metadata": updated,
                "citation_key": read["citation_key"],
            },
        )
        assert response.status_code == 200
        saved = (await client.get(path)).json()
        assert saved["metadata"] == updated and saved["citation_key"] == "ManualKey"
        preserved = await client.put(
            path, json={"expected_version": saved["version"], "metadata": updated}
        )
        assert preserved.status_code == 200
        saved = (await client.get(path)).json()
        assert saved["citation_key"] == "ManualKey"
        cleared = await client.put(
            path,
            json={"expected_version": saved["version"], "metadata": updated, "citation_key": None},
        )
        assert cleared.status_code == 200
        assert (await client.get(path)).json()["citation_key"] is None
        assert (await client.get(f"{path}/overview")).json()["citation_key"] is None
        stale = await client.put(path, json={"expected_version": read["version"], "metadata": work})
        assert stale.status_code == 409
        assert (await client.get(path)).json()["metadata"] == updated
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "patch",
    [
        {"type": "invented"},
        {"title": 42},
        {"date_published": "2023-02-29"},
        {"custom_fields": {"rating": 5}},
        {
            "contributors": [
                {"type": "Person", "organization": {"name": "wrong variant"}, "roles": ["Author"]}
            ]
        },
        {"contributors": [{"type": "Person", "person": {"name": "Smith"}, "roles": ["invented"]}]},
    ],
)
async def test_http_invalid_work_is_rejected_atomically(
    async_db, async_session_factory, tmp_path, monkeypatch, patch
):
    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    seed_id = seed.id
    try:
        base = f"/api/v1/workspaces/{seed.workspace_id}/items"
        response = await client.post(base, json={"metadata": metadata() | patch})
        assert response.status_code == 422
        assert (await async_db.scalars(select(Item.id))).all() == [seed_id]
        assert (
            await async_db.scalar(select(AuditEvent).where(AuditEvent.action == "item.create"))
            is None
        )
    finally:
        await client.aclose()


async def test_work_schema_is_workspace_authorized(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.get(f"/api/v1/workspaces/{seed.workspace_id}/metadata/schema")
        assert response.status_code == 200
        assert response.json()["$defs"]["work"]["required"] == ["id", "type"]
        assert (
            await client.get(f"/api/v1/workspaces/{uuid4()}/metadata/schema")
        ).status_code == 404
        client.cookies.clear()
        assert (
            await client.get(f"/api/v1/workspaces/{seed.workspace_id}/metadata/schema")
        ).status_code == 401
    finally:
        await client.aclose()


async def test_given_name_only_author_suggestions_are_valid_http_responses(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{seed.workspace_id}"
    try:
        response = await client.post(
            f"{base}/items",
            json={
                "metadata": metadata()
                | {
                    "contributors": [
                        {"type": "Person", "person": {"given_name": "Ada"}, "roles": ["Author"]}
                    ]
                }
            },
        )
        assert response.status_code == 201
        response = await client.get(f"{base}/authors", params={"query": "Ada"})
        assert response.status_code == 200
        assert response.json() == [{"last_name": "Ada", "first_name": None, "full_name": "Ada"}]
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "path",
    ["bibliography?file_format=csl-json", "bibliography?file_format=csl", "citation/content"],
)
async def test_unsupported_csl_export_returns_a_validation_error(
    async_db, async_session_factory, tmp_path, monkeypatch, path
):
    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{seed.workspace_id}/items"
    try:
        created = await client.post(
            base, json={"metadata": metadata() | {"type": "ProceedingsArticle"}}
        )
        assert created.status_code == 201
        response = await client.get(f"{base}/{created.json()['id']}/{path}")
        assert response.status_code == 422
        assert "CSL" in response.text
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "bad", ["@article{bad,title=undefinedmacro}", "@article{bad,title={Invalid}"]
)
@pytest.mark.parametrize("bad_first", [False, True])
async def test_bibtex_parse_failure_stages_valid_siblings_over_http(
    async_db, async_session_factory, tmp_path, monkeypatch, bad, bad_first
):
    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{seed.workspace_id}"
    valid = "@article{good,title={Valid sibling},doi={10.1234/good}}"
    content = "\n".join([bad, valid] if bad_first else [valid, bad]).encode()
    try:
        response = await client.post(
            f"{base}/imports/bibliography",
            files={
                "bibliography": (
                    "records.bib",
                    content,
                    "application/x-bibtex",
                )
            },
            data={"file_format": "bibtex"},
        )
        assert response.status_code == 201
        preview = response.json()
        assert len(preview["records"]) == 1
        assert any(
            error["row"] == (1 if bad_first else 2) and error["code"] == "invalid_record"
            for error in preview["errors"]
        )
        assert (await client.post(f"{base}/imports/{preview['id']}/commit")).status_code == 200
        assert (await client.post(f"{base}/imports/{preview['id']}/commit")).status_code == 200
        assert (
            len(
                (
                    await async_db.scalars(
                        select(Item).where(Item.work["title"].as_string() == "Valid sibling")
                    )
                ).all()
            )
            == 1
        )
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "path",
    ["bibliography?file_format=csl-json", "bibliography?file_format=csl", "citation/content"],
)
async def test_licensed_article_citation_endpoints_remain_supported(
    async_db, async_session_factory, tmp_path, monkeypatch, path
):
    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{seed.workspace_id}/items"
    work = metadata() | {
        "type": "JournalArticle",
        "title": "Licensed article",
        "license": {"id": "CC-BY-4.0", "url": "https://creativecommons.org/licenses/by/4.0/"},
    }
    try:
        created = await client.post(base, json={"metadata": work})
        assert created.status_code == 201
        item_path = f"{base}/{created.json()['id']}"
        response = await client.get(f"{item_path}/{path}")
        assert response.status_code == 200
        assert "Licensed article" in response.text
        assert (await client.get(item_path)).json()["metadata"] == work
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "path",
    ["bibliography?file_format=csl-json", "bibliography?file_format=csl", "citation/content"],
)
async def test_versioned_software_citations_are_explicit_errors(
    async_db, async_session_factory, tmp_path, monkeypatch, path
):
    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{seed.workspace_id}/items"
    try:
        created = await client.post(
            base,
            json={
                "metadata": {
                    "id": "urn:uuid:00000000-0000-4000-8000-000000000001",
                    "type": "Software",
                    "title": "Software",
                    "version": "1.0",
                }
            },
        )
        assert created.status_code == 201
        response = await client.get(f"{base}/{created.json()['id']}/{path}")
        assert response.status_code == 422
        assert "Software" in response.text
    finally:
        await client.aclose()


async def test_bibtex_download_preserves_organization_credit_and_safe_title(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    import bibtexparser

    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{seed.workspace_id}/items"
    work = {
        "id": "https://doi.org/10.1000/export_safe",
        "type": "JournalArticle",
        "title": "A <i>50%</i> improvement in R&amp;D costs",
        "contributors": [
            {
                "type": "Organization",
                "organization": {"name": "Research and Development Corp."},
                "roles": ["Author"],
            }
        ],
    }
    try:
        created = await client.post(base, json={"metadata": work, "citation_key": "safe"})
        assert created.status_code == 201
        item_path = f"{base}/{created.json()['id']}"
        response = await client.get(f"{item_path}/bibliography?file_format=bibtex")
        assert response.status_code == 200
        entry = bibtexparser.loads(response.text).entries[0]
        assert entry["ID"] == "safe"
        assert entry["author"] == "{Research and Development Corp.}"
        assert entry["title"] == r"A \textit{50\%} improvement in R\&D costs"
        assert (await client.get(item_path)).json()["metadata"] == work
    finally:
        await client.aclose()


async def test_html_citation_download_sanitizes_stored_rich_text(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    from html.parser import HTMLParser

    class CitationMarkup(HTMLParser):
        def handle_starttag(self, tag, attrs):
            assert tag in {"i", "b", "sup", "sub"}
            assert attrs == []

    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{seed.workspace_id}/items"
    work = {
        "id": "https://doi.org/10.1000/citation",
        "type": "JournalArticle",
        "title": 'Research<script>alert(1)</script><i onclick="alert(2)">Safe</i><img src=x onerror=alert(3)>',
    }
    try:
        created = await client.post(base, json={"metadata": work})
        assert created.status_code == 201
        item_path = f"{base}/{created.json()['id']}"
        response = await client.get(f"{item_path}/citation/content?output=html")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "Research" in response.text and "safe" in response.text.lower()
        assert "alert(" not in response.text
        CitationMarkup().feed(response.text)
        assert (await client.get(item_path)).json()["metadata"] == work
    finally:
        await client.aclose()


@pytest.mark.parametrize(
    "primary,namespace,value,identifier_type,secondary",
    [
        ("https://openalex.org/W123", "openalex", "W123", "OpenAlex", "https://openalex.org/W123"),
        ("https://pubmed.ncbi.nlm.nih.gov/42/", "pmid", "42", "PMID", "42"),
        ("https://arxiv.org/abs/2401.00001", "arxiv", "2401.00001", "arXiv", "2401.00001"),
    ],
)
@pytest.mark.parametrize("also_secondary", [False, True])
async def test_overview_exposes_missing_primary_lookup_context(
    async_db,
    async_session_factory,
    tmp_path,
    monkeypatch,
    primary,
    namespace,
    value,
    identifier_type,
    secondary,
    also_secondary,
):
    client, seed, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{seed.workspace_id}/items"
    work = {
        "id": primary,
        "type": "Preprint",
        "title": "Primary identifier",
        **(
            {"identifiers": [{"identifier_type": identifier_type, "identifier": secondary}]}
            if also_secondary
            else {}
        ),
    }
    try:
        created = await client.post(base, json={"metadata": work})
        assert created.status_code == 201
        response = await client.get(f"{base}/{created.json()['id']}/overview")
        assert response.status_code == 200
        overview = response.json()
        assert overview.get("primary_lookup_identifier") == (
            None if also_secondary else {"provider": namespace, "value": value}
        )
        assert overview["metadata"] == work
    finally:
        await client.aclose()
