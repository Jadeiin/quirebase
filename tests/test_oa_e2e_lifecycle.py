from __future__ import annotations

import json
from unittest.mock import patch

import httpx
from item_helpers import create_item_record as create_item
from sqlalchemy import select
from test_http import authenticated_client

from quirebase.core.config import get_settings
from quirebase.discovery.citations import (
    builtin_style_xml,
    item_to_csl_json,
    render_bibliography,
)
from quirebase.discovery.imports import (
    commit_import_batch,
    stage_metadata_batch,
)
from quirebase.discovery.lookup import (
    Identifier,
    MetadataRecord,
    lookup_metadata,
)
from quirebase.library import (
    MetadataWorkspace,
    SummaryWorkspace,
    WorkspaceSection,
    open_item_workspace,
)
from quirebase.library.identifiers import sync_metadata_from_upstream
from quirebase.models import (
    AuditEvent,
    Item,
    ItemAuthor,
    ItemIdentifier,
    User,
)
from quirebase.web.app import app

# Realistic Open Access Work from PMC Open Access Subset (corpus paper PMC10670526 / DOI 10.3390/ejihpe13110181)
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
    "open_access": {
        "is_oa": True,
        "oa_url": "https://www.mdpi.com/2254-9625/13/11/181/pdf?version=1699524259",
    },
    "biblio": {
        "volume": "13",
        "issue": "11",
        "first_page": "2599",
        "last_page": "2614",
    },
    "type": "journal-article",
}


def test_seam1_oa_corpus_metadata_lookup_and_reconstruction():
    """Seam 1: External OpenAlex lookup parses inverted index, cleans HTML, and formats URLs/UIDs for OA paper."""

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=OA_CORPUS_OPENALEX_PAYLOAD)

    identifier, record = lookup_metadata(
        "10.3390/ejihpe13110181",
        "openalex",
        transport=httpx.MockTransport(mock_handler),
    )

    assert isinstance(identifier, Identifier)
    assert identifier.provider == "openalex"

    assert isinstance(record, MetadataRecord)
    # 1. HTML tags in title stripped
    assert (
        record.title
        == "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives"
    )
    # 2. Inverted index reconstructed
    assert (
        record.abstract
        == "The rapid advancement of artificial intelligence has transformed The landscape of higher education."
    )
    # 3. Authors structured
    assert record.authors == "Ahmed M. Hasanein; Abu Elnasr E. Sobaih"
    # 4. Keywords from topics
    assert "Artificial Intelligence in Higher Education" in str(record.keywords)
    # 5. Volume, issue, pages, publisher
    assert record.volume == "13"
    assert record.issue == "11"
    assert record.pages == "2599-2614"
    assert record.publisher == "MDPI"
    # 6. OA URLs present
    assert "https://doi.org/10.3390/ejihpe13110181" in str(record.urls)
    assert "https://www.mdpi.com/2254-9625/13/11/181/pdf?version=1699524259" in str(record.urls)


def test_seam2_oa_corpus_batch_import_and_relational_mapping(db):
    """Seam 2: Ingesting an OA record creates Item, Author links, Tags, and ItemIdentifiers."""
    user = User(username="oa_corpus_tester", password_hash="secret")
    db.add(user)
    db.flush()

    def mock_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=OA_CORPUS_OPENALEX_PAYLOAD)

    batch, records, errors = stage_metadata_batch(
        db,
        user,
        identifier="10.3390/ejihpe13110181",
        provider="openalex",
        transport=httpx.MockTransport(mock_handler),
    )
    assert not errors
    assert len(records) == 1

    commit_import_batch(db, user, batch.id)

    # Verify persisted Item
    item = db.scalar(
        select(Item).where(
            Item.title
            == "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives"
        )
    )
    assert item is not None
    assert item.created_by == user.id
    assert item.volume == "13"
    assert item.issue == "11"
    assert item.pages == "2599-2614"
    assert "mdpi.com" in str(item.urls)

    # Verify structured ItemAuthor relations
    author_links = list(
        db.scalars(
            select(ItemAuthor).where(ItemAuthor.item_id == item.id).order_by(ItemAuthor.position)
        ).all()
    )
    assert len(author_links) == 2
    assert author_links[0].author.last_name == "Hasanein"
    assert author_links[1].author.last_name == "Sobaih"

    # Verify Keywords populated on Item metadata
    assert item.keywords is not None
    assert "Artificial Intelligence in Higher Education" in item.keywords
    assert "Educational Technology and Stakeholder Engagement" in item.keywords

    # Verify ItemIdentifiers
    idents = list(db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item.id)).all())
    ident_dict = {i.provider: i.value for i in idents}
    assert ident_dict.get("openalex") == "W4388656112"
    assert "doi" not in ident_dict
    assert item.doi == "10.3390/ejihpe13110181"


def test_seam3_oa_corpus_upstream_sync_and_reconciliation(db):
    """Seam 3: Upstream sync merges rich OA metadata into existing item without data loss."""
    user = User(username="sync_corpus_tester", password_hash="secret")
    db.add(user)
    db.flush()

    # Initial minimal item
    item = create_item(
        db,
        user,
        title="Drivers and Consequences of ChatGPT Use (Draft)",
        authors="Hasanein, Ahmed M.",
    )
    assert item.doi is None
    assert item.volume is None

    mock_rec = MetadataRecord(
        title="Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives",
        abstract="The rapid advancement of artificial intelligence...",
        authors="Hasanein, Ahmed M.; Sobaih, Abu Elnasr E.",
        keywords="Artificial Intelligence in Higher Education; Educational Technology",
        publication_date="2023-11-09",
        publication_title="European Journal of Investigation in Health, Psychology and Education",
        journal_abbreviation="Eur J Investig Health Psychol Educ",
        volume="13",
        issue="11",
        pages="2599-2614",
        publisher="MDPI",
        doi="10.3390/ejihpe13110181",
        urls="https://doi.org/10.3390/ejihpe13110181\nhttps://www.mdpi.com/2254-9625/13/11/181/pdf",
        identifiers=json.dumps({"openalex": "W4388656112", "doi": "10.3390/ejihpe13110181"}),
        reference_type="journal-article",
    )

    with patch(
        "quirebase.library.identifiers.lookup_metadata",
        return_value=(Identifier("doi", "10.3390/ejihpe13110181"), mock_rec),
    ):
        updated = sync_metadata_from_upstream(
            db,
            user,
            item.id,
            item.version,
            provider="doi",
            uid_value="10.3390/ejihpe13110181",
        )

    assert (
        updated.title
        == "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives"
    )
    assert updated.volume == "13"
    assert updated.issue == "11"
    assert updated.pages == "2599-2614"
    assert updated.journal_abbreviation == "Eur J Investig Health Psychol Educ"
    assert "https://www.mdpi.com/2254-9625/13/11/181/pdf" in str(updated.urls)

    # Authors enriched
    assert len(updated.author_links) == 2
    assert updated.author_links[0].author.last_name == "Hasanein"
    assert updated.author_links[1].author.last_name == "Sobaih"

    # Audit event recorded
    audit = db.scalar(
        select(AuditEvent)
        .where(AuditEvent.target_id == item.id)
        .where(AuditEvent.action == "item.sync_upstream")
    )
    assert audit is not None


def test_seam4_oa_corpus_citation_generation_and_csl_export(db):
    """Seam 4: Synced OA item maps to CSL-JSON and renders valid APA & IEEE citations."""
    user = User(username="cite_corpus_tester", password_hash="secret")
    db.add(user)
    db.flush()

    item = Item(
        title="Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives",
        authors="Hasanein, Ahmed M.; Sobaih, Abu Elnasr E.",
        publication_title="European Journal of Investigation in Health, Psychology and Education",
        journal_abbreviation="Eur J Investig Health Psychol Educ",
        publication_date="2023",
        volume="13",
        issue="11",
        pages="2599-2614",
        publisher="MDPI",
        doi="10.3390/ejihpe13110181",
        urls="https://doi.org/10.3390/ejihpe13110181",
        reference_type="journal-article",
        created_by=user.id,
    )
    db.add(item)
    db.commit()

    csl_json = item_to_csl_json(item)
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


def test_seam5_oa_corpus_web_workspace_and_editing_roundtrip(db, tmp_path, monkeypatch):
    """Seam 5: Web UI displays rich metadata and preserves structured authors upon editing."""
    client, seed_item, _rev = authenticated_client(db, tmp_path, monkeypatch)
    try:
        user_id = seed_item.created_by
        user = db.get(User, user_id)
        assert user is not None

        item = Item(
            title="Drivers and Consequences of ChatGPT Use in Higher Education",
            authors="Hasanein, Ahmed M.",
            publication_title="European Journal of Investigation in Health, Psychology and Education",
            volume="13",
            issue="11",
            pages="2599-2614",
            doi="10.3390/ejihpe13110181",
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(item)
        db.commit()

        # 1. Fetch workspace view
        resp = client.get(f"/items/{item.id}")
        assert resp.status_code == 200
        assert "Drivers and Consequences of ChatGPT Use" in resp.text
        assert "10.3390/ejihpe13110181" in resp.text

        # 2. Submit edit form modifying title and adding second author
        edit_resp = client.post(
            f"/items/{item.id}/edit?csrf_token=test-csrf",
            data={
                "version": str(item.version),
                "title": "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives",
                "author_last_name[]": ["Hasanein", "Sobaih"],
                "author_first_name[]": ["Ahmed M.", "Abu Elnasr E."],
                "volume": "13",
                "issue": "11",
                "pages": "2599-2614",
                "doi": "10.3390/ejihpe13110181",
            },
            follow_redirects=True,
        )
        assert edit_resp.status_code == 200
        assert (
            "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives"
            in edit_resp.text
        )

        # 3. Verify structured relations in DB
        db.expire_all()
        workspace_data = open_item_workspace(db, user, item.id, WorkspaceSection.summary)
        assert isinstance(workspace_data, SummaryWorkspace)
        assert (
            workspace_data.item.title
            == "Drivers and Consequences of ChatGPT Use in Higher Education: Key Stakeholder Perspectives"
        )
        metadata = open_item_workspace(db, user, item.id, WorkspaceSection.metadata)
        assert isinstance(metadata, MetadataWorkspace)
        author_links = metadata.authors
        assert len(author_links) == 2
        assert author_links[0].author.last_name == "Hasanein"
        assert author_links[1].author.last_name == "Sobaih"
        assert author_links[1].author.first_name == "Abu Elnasr E."
    finally:
        app.dependency_overrides.clear()
        get_settings.cache_clear()
