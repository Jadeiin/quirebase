from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx2
import pytest
from app_helpers import json_payload
from commonmeta.author_utils import get_one_author
from commonmeta.base_utils import compact
from inquiro import CandidateRecord, Identifier
from inquiro.bibliography import builtin_style_xml, render_bibliography, work_to_csl_json
from inquiro.work import work_identifiers
from item_helpers import contributor_values, stored_doi, work_identifier
from item_helpers import create_item_record as create_item
from provider_helpers import provider_runtime
from sqlalchemy import select
from test_http import authenticated_async_client
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.access import resolve_workspace_context
from quirebase.core.config import get_settings
from quirebase.library import ItemMetadataData, ItemOverviewData, ItemSection, open_item_section
from quirebase.library.identifiers import sync_metadata_from_upstream
from quirebase.library.imports import commit_import_batch, stage_identifier_import_batch
from quirebase.models import AuditEvent, Item, User

OA_CORPUS_OPENALEX_PAYLOAD = {
    "id": "https://openalex.org/W4388656112",
    "doi": "https://doi.org/10.3390/ejihpe13110181",
    "title": "Drivers and Consequences of <i>ChatGPT</i> Use in Higher Education: Key Stakeholder Perspectives",
    "display_name": "Drivers and Consequences of <i>ChatGPT</i> Use in Higher Education: Key Stakeholder Perspectives",
    "publication_date": "2023-11-09",
    "abstract_inverted_index": {
        "The": [0, 8],
        "rapid": [1],
        "advancement": [2],
        "of": [3, 10],
        "artificial": [4],
        "intelligence": [5],
        "has": [6],
        "transformed": [7],
        "landscape": [9],
        "higher": [11],
        "education.": [12],
    },
    "authorships": [
        {
            "author_position": "first",
            "author": {"display_name": "Ahmed M. Hasanein"},
            "institutions": [{"display_name": "King Faisal University"}],
        },
        {
            "author_position": "last",
            "author": {"display_name": "Abu Elnasr E. Sobaih"},
            "institutions": [{"display_name": "King Faisal University"}],
        },
    ],
    "topics": [
        {"display_name": "Artificial Intelligence in Higher Education"},
        {"display_name": "Educational Technology and Stakeholder Engagement"},
    ],
    "primary_location": {
        "source": {
            "display_name": "European Journal of Investigation in Health, Psychology and Education",
            "host_organization_name": "MDPI",
        },
        "landing_page_url": "https://www.mdpi.com/2254-9625/13/11/181",
        "is_oa": True,
    },
    "best_oa_location": {
        "pdf_url": "https://www.mdpi.com/2254-9625/13/11/181/pdf?version=1699524259"
    },
    "biblio": {"volume": "13", "issue": "11", "first_page": "2599", "last_page": "2614"},
    "type": "journal-article",
}


@pytest.mark.anyio
async def test_seam1_oa_corpus_metadata_lookup_and_reconstruction():
    """Seam 1: External OpenAlex lookup parses inverted index, cleans HTML, and formats URLs/UIDs for OA paper."""

    def mock_handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=json_payload(OA_CORPUS_OPENALEX_PAYLOAD))

    async with provider_runtime(transport=httpx2.MockTransport(mock_handler)) as runtime:
        record = await runtime.lookup("10.3390/ejihpe13110181", provider="openalex")
    identifier = record.lookup_identifier
    assert isinstance(identifier, Identifier)
    assert identifier.provider == "openalex"
    assert isinstance(record, CandidateRecord)
    assert (
        record.work.get("title")
        == "Drivers and Consequences of <i>ChatGPT</i> Use in Higher Education: Key Stakeholder Perspectives"
    )
    assert (
        record.work.get("description")
        == "The rapid advancement of artificial intelligence has transformed The landscape of higher education."
    )
    assert [person["person"]["family_name"] for person in record.work["contributors"]] == [
        "Hasanein",
        "Sobaih",
    ]
    assert record.work.get("container", {}).get("volume") == "13"
    assert record.work.get("container", {}).get("issue") == "11"
    assert record.work.get("container", {}).get("first_page") == "2599"
    assert record.work.get("publisher", {}).get("name") == "MDPI"
    assert "https://doi.org/10.3390/ejihpe13110181" in str(record.work)
    assert "https://www.mdpi.com/2254-9625/13/11/181/pdf?version=1699524259" in str(record.work)


@pytest.mark.anyio
async def test_seam2_oa_corpus_batch_import_and_relational_mapping(async_db, monkeypatch):
    """Seam 2: Ingesting an OA record creates Item metadata, Tags, and standard Work identifiers."""
    db = async_db
    user = User(username="oa_corpus_tester", password_hash="secret")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    await db.commit()
    user_id = user.id

    def mock_handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json=json_payload(OA_CORPUS_OPENALEX_PAYLOAD))

    monkeypatch.setattr(
        "quirebase.library.providers.provider_runtime",
        lambda settings: provider_runtime(
            settings=settings, transport=httpx2.MockTransport(mock_handler)
        ),
    )
    batch = await stage_identifier_import_batch(
        db,
        user,
        fixture_workspace_id(user),
        identifier="10.3390/ejihpe13110181",
        provider="openalex",
    )
    records = batch.records
    errors = batch.errors
    assert all(error.severity == "warning" for error in errors)
    assert len(records) == 1
    await commit_import_batch(db, user, fixture_workspace_id(user), batch.id)
    item = await db.scalar(
        select(Item).where(
            Item.work["title"].as_string()
            == "Drivers and Consequences of <i>ChatGPT</i> Use in Higher Education: Key Stakeholder Perspectives"
        )
    )
    assert item is not None
    assert item.created_by == user_id
    assert item.work.get("container", {}).get("volume") == "13"
    assert item.work.get("container", {}).get("issue") == "11"
    assert item.work.get("container", {}).get("first_page") == "2599"
    assert "mdpi.com" in str(item.work)
    assert len(item.work["contributors"]) == 2
    assert item.work["contributors"][0]["person"]["family_name"] == "Hasanein"
    assert item.work["contributors"][1]["person"]["family_name"] == "Sobaih"
    ident_dict = dict(work_identifiers(item.work))
    assert ident_dict.get("openalex") == "W4388656112"
    assert ident_dict["doi"] == "10.3390/ejihpe13110181"
    assert stored_doi(item) == "10.3390/ejihpe13110181"


@pytest.mark.anyio
async def test_seam3_oa_corpus_upstream_sync_and_reconciliation(async_db):
    """Seam 3: Upstream sync merges rich OA metadata into existing item without data loss."""
    db = async_db
    user = User(username="sync_corpus_tester", password_hash="secret")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    item = await create_item(
        db,
        user,
        title="Drivers and Consequences of ChatGPT Use (Draft)",
        authors="Hasanein, Ahmed M.",
    )
    assert stored_doi(item) is None
    assert item.work.get("container", {}).get("volume") is None
    mock_rec = CandidateRecord(
        provider="crossref",
        lookup_identifier=Identifier("doi", "10.3390/ejihpe13110181"),
        work=compact({
            "id": f"urn:uuid:{uuid4()}",
            "type": "JournalArticle",
            "title": "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives",
            "description": "The rapid advancement of artificial intelligence...",
            "date_published": "2023-11-09",
            "contributors": (
                get_one_author({"name": "Hasanein, Ahmed M."}),
                get_one_author({"name": "Sobaih, Abu Elnasr E."}),
            ),
            "container": {
                "title": "European Journal of Investigation in Health, Psychology and Education",
                "volume": "13",
                "issue": "11",
                "first_page": "2599-2614",
                "additional_titles": ["Eur J Investig Health Psychol Educ"],
            },
            "publisher": {"name": "MDPI"},
            "subjects": [
                {"subject": v}
                for v in ("Artificial Intelligence in Higher Education", "Educational Technology")
            ],
            "identifiers": [
                work_identifier("openalex", "W4388656112"),
                work_identifier("doi", "10.3390/ejihpe13110181"),
            ],
        }),
    )
    with patch(
        "quirebase.library.identifiers.lookup_candidate", new=AsyncMock(return_value=mock_rec)
    ):
        updated = await sync_metadata_from_upstream(
            db,
            user,
            fixture_workspace_id(user),
            item.id,
            item.version,
            provider="doi",
            uid_value="10.3390/ejihpe13110181",
        )
    assert (
        updated.work.get("title")
        == "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives"
    )
    assert updated.work.get("container", {}).get("volume") == "13"
    assert updated.work.get("container", {}).get("issue") == "11"
    assert updated.work.get("container", {}).get("first_page") == "2599-2614"
    assert updated.work.get("container", {}).get("additional_titles") == [
        "Eur J Investig Health Psychol Educ"
    ]
    assert len(updated.work["contributors"]) == 2
    assert updated.work["contributors"][0]["person"]["family_name"] == "Hasanein"
    assert updated.work["contributors"][1]["person"]["family_name"] == "Sobaih"
    audit = await db.scalar(
        select(AuditEvent)
        .where(AuditEvent.target_id == str(item.id))
        .where(AuditEvent.action == "item.sync_upstream")
    )
    assert audit is not None


@pytest.mark.anyio
async def test_seam4_oa_corpus_citation_generation_and_csl_export(async_db):
    """Seam 4: Synced OA item maps to CSL-JSON and renders valid APA & IEEE citations."""
    db = async_db
    user = User(username="cite_corpus_tester", password_hash="secret")
    db.add(user)
    await db.flush()
    await provision_initial_workspace(db, user)
    item = Item(
        workspace_id=fixture_workspace_id(user),
        created_by=user.id,
        work={
            "id": f"urn:uuid:{uuid4()}",
            "type": "JournalArticle",
            "title": "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives",
            "date_published": "2023",
            "contributors": contributor_values("Hasanein, Ahmed M.; Sobaih, Abu Elnasr E."),
            "container": {
                "title": "European Journal of Investigation in Health, Psychology and Education",
                "volume": "13",
                "issue": "11",
                "first_page": "2599-2614",
                "additional_titles": ["Eur J Investig Health Psychol Educ"],
            },
            "publisher": {"name": "MDPI"},
            "identifiers": [{"identifier_type": "DOI", "identifier": "10.3390/ejihpe13110181"}],
        },
    )
    db.add(item)
    await db.commit()
    csl_json = work_to_csl_json(item.work)
    assert (
        csl_json["title"]
        == "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives"
    )
    assert csl_json["DOI"] == "10.3390/ejihpe13110181"
    assert csl_json["volume"] == "13"
    assert csl_json["issue"] == "11"
    assert csl_json["page"] == "2599-2614"
    assert (
        csl_json["container-title"]
        == "European Journal of Investigation in Health, Psychology and Education"
    )
    assert len(csl_json["author"]) == 2
    assert csl_json["author"][0]["family"] == "Hasanein"
    assert csl_json["author"][1]["family"] == "Sobaih"
    apa_xml = builtin_style_xml("apa")
    rendered = render_bibliography([csl_json], apa_xml)
    assert len(rendered) == 1
    assert "Hasanein, A. M." in rendered[0]
    assert "Sobaih, A. E. E." in rendered[0]
    assert "ChatGPT Use in Higher Education" in rendered[0]
    assert "2599" in rendered[0] and "2614" in rendered[0]
    assert "https://doi.org/10.3390/ejihpe13110181" in rendered[0]


@pytest.mark.anyio
async def test_seam5_oa_corpus_web_workspace_and_editing_roundtrip(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    """Seam 5: Web UI displays rich metadata and preserves structured authors upon editing."""
    db = async_db
    client, seed_item, _rev = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        user_id = seed_item.created_by
        user = await db.get(User, user_id)
        assert user is not None
        item = Item(
            workspace_id=seed_item.workspace_id,
            created_by=user_id,
            updated_by=user_id,
            work={
                "id": f"urn:uuid:{uuid4()}",
                "type": "Document",
                "title": "Drivers and Consequences of ChatGPT Use in Higher Education",
                "contributors": contributor_values("Hasanein, Ahmed M."),
                "container": {
                    "title": "European Journal of Investigation in Health, Psychology and Education",
                    "volume": "13",
                    "issue": "11",
                    "first_page": "2599-2614",
                },
                "identifiers": [{"identifier_type": "DOI", "identifier": "10.3390/ejihpe13110181"}],
            },
        )
        db.add(item)
        await db.commit()
        item_id = item.id
        item_version = item.version
        resp = await client.get(f"/api/v1/workspaces/{seed_item.workspace_id}/items/{item_id}")
        assert resp.status_code == 200
        assert resp.json()["title_html"] == item.work.get("title")
        assert resp.json()["doi"] == "10.3390/ejihpe13110181"
        edit_resp = await client.put(
            f"/api/v1/workspaces/{seed_item.workspace_id}/items/{item_id}",
            json=json_payload({
                "expected_version": item_version,
                "metadata": {
                    "id": "https://doi.org/10.3390/ejihpe13110181",
                    "type": "Document",
                    "title": "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives",
                    "container": {
                        "title": item.work.get("container", {}).get("title"),
                        "volume": "13",
                        "issue": "11",
                        "first_page": "2599-2614",
                    },
                    "contributors": [
                        {
                            "type": "Person",
                            "person": {
                                "family_name": "Hasanein",
                                "given_name": "Ahmed M.",
                                "name": "Hasanein, Ahmed M.",
                            },
                            "roles": ["Author"],
                        },
                        {
                            "type": "Person",
                            "person": {
                                "family_name": "Sobaih",
                                "given_name": "Abu Elnasr E.",
                                "name": "Sobaih, Abu Elnasr E.",
                            },
                            "roles": ["Author"],
                        },
                    ],
                },
            }),
        )
        assert edit_resp.status_code == 200
        edited = await client.get(f"/api/v1/workspaces/{seed_item.workspace_id}/items/{item_id}")
        assert (
            edited.json()["title_html"]
            == "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives"
        )
        workspace_id = seed_item.workspace_id
        db.expire_all()
        user = await db.get(User, user_id)
        assert user is not None
        overview = await open_item_section(
            db,
            await resolve_workspace_context(db, user, workspace_id),
            item_id,
            ItemSection.overview,
        )
        assert isinstance(overview, ItemOverviewData)
        assert (
            overview.item.work.get("title")
            == "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives"
        )
        metadata = await open_item_section(
            db,
            await resolve_workspace_context(db, user, workspace_id),
            item_id,
            ItemSection.metadata,
        )
        assert isinstance(metadata, ItemMetadataData)
        contributors = [credit.person for credit in metadata.metadata.contributors]
        assert len(contributors) == 2
        assert contributors[0].family_name == "Hasanein"
        assert contributors[1].family_name == "Sobaih"
        assert contributors[1].given_name == "Abu Elnasr E."
    finally:
        await client.aclose()
        get_settings.cache_clear()
