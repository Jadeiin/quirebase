from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from inquiro import CandidateRecord, Identifier
from sqlalchemy import func, select
from test_http import authenticated_async_client
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.errors import ResourceNotFound, UpstreamServiceError, ValidationFailure
from quirebase.models import (
    Author,
    Item,
    ItemAuthor,
    ItemIdentifier,
    ItemTag,
    ItemTagRecommendation,
    SystemSetting,
    Tag,
    User,
)


@pytest.mark.anyio
async def test_http_api_creates_complete_metadata(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"

    response = await client.post(
        f"{workspace_base}/items",
        json={
            "title": "Complete manual record",
            "abstract": "All editable metadata is accepted during creation.",
            "reference_type": "article",
            "publication_date": "2026-08-17",
            "publication_title": "Journal of Complete Forms",
            "journal_abbreviation": "JCF",
            "volume": "12",
            "issue": "3",
            "pages": "10-20",
            "affiliation": "Quirebase Lab",
            "publisher": "Example Press",
            "place_published": "Shanghai",
            "doi": "https://doi.org/10.1000/complete",
            "bibtex_key": "complete2026record",
            "bibtex_type": "article",
            "urls": ["https://example.test/record", "https://example.test/pdf"],
            "keywords": ["forms", "metadata"],
            "identifiers": [{"provider": "pmid", "value": "12345"}],
            "custom_fields": [{"name": "rating", "value": 5}],
            "authors": [
                {"last_name": "Lovelace", "first_name": "Ada", "is_corresponding": True},
                {"last_name": "Turing", "first_name": "Alan"},
            ],
            "editors": [{"last_name": "Hopper", "first_name": "Grace"}],
        },
    )

    assert response.status_code == 201
    created = await db.scalar(select(Item).where(Item.title == "Complete manual record"))
    assert created is not None
    assert response.json() == {"id": created.id, "version": 1}
    assert created.authors == "Lovelace, Ada; Turing, Alan"
    assert created.editors == "Hopper, Grace"
    assert created.doi == "10.1000/complete"
    assert json.loads(created.identifiers or "") == {"pmid": "12345"}
    assert created.keywords == "forms; metadata"
    assert created.urls == "https://example.test/record\nhttps://example.test/pdf"
    assert json.loads(created.custom_fields or "") == {"rating": 5}
    await client.aclose()


@pytest.mark.anyio
async def test_http_api_edits_rich_metadata_and_structured_contributors(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id
    response = await client.put(
        f"{workspace_base}/items/{item_id}",
        json={
            "expected_version": item.version,
            "metadata": {
                "title": "Attention Is All You Need",
                "abstract": "The dominant sequence transduction models are based on complex recurrent networks.",
                "reference_type": "conference",
                "publication_date": "2017-06-12",
                "publication_title": "Advances in Neural Information Processing Systems",
                "journal_abbreviation": "NeurIPS",
                "volume": "30",
                "issue": "1",
                "pages": "5998-6008",
                "affiliation": "Google Brain",
                "publisher": "Curran Associates, Inc.",
                "place_published": "Long Beach, CA",
                "doi": "10.5555/3295222.3295349",
                "bibtex_key": "vaswani2017attention",
                "bibtex_type": "inproceedings",
                "urls": [
                    "https://arxiv.org/abs/1706.03762",
                    "https://proceedings.neurips.cc/paper/7181",
                ],
                "custom_fields": [
                    {"name": "rating", "value": 5},
                    {"name": "flags", "value": ["reviewed"]},
                    {"name": "meta", "value": {"source": "manual"}},
                ],
                "authors": [
                    {"last_name": "Vaswani", "first_name": "Ashish", "is_corresponding": True},
                    {"last_name": "Shazeer", "first_name": "Noam"},
                    {"last_name": "Parmar", "first_name": "Niki"},
                ],
                "editors": [
                    {"last_name": "Guyon", "first_name": "Isabelle"},
                    {"last_name": "von Luxburg", "first_name": "Ulrike"},
                ],
            },
        },
    )
    assert response.status_code == 200

    db.expire_all()
    updated = await db.get(Item, item_id)
    assert updated is not None
    assert updated.title == "Attention Is All You Need"
    assert updated.journal_abbreviation == "NeurIPS"
    assert updated.volume == "30"
    assert updated.pages == "5998-6008"
    assert updated.affiliation == "Google Brain"
    assert updated.bibtex_id == "vaswani2017attention"
    assert json.loads(updated.custom_fields or "") == {
        "rating": 5,
        "flags": ["reviewed"],
        "meta": {"source": "manual"},
    }
    assert updated.updated_by is not None
    assert updated.authors == "Vaswani, Ashish; Shazeer, Noam; Parmar, Niki"
    assert updated.editors == "Guyon, Isabelle; von Luxburg, Ulrike"

    # Verify ItemAuthor links
    authors = list(
        await db.scalars(
            select(ItemAuthor)
            .where(ItemAuthor.item_id == item_id, ItemAuthor.role == "author")
            .order_by(ItemAuthor.position)
        )
    )
    assert len(authors) == 3
    assert authors[0].is_corresponding is True
    assert authors[1].is_corresponding is False
    await client.aclose()


@pytest.mark.anyio
async def test_http_api_tag_matrix_and_selection(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id
    item.keywords = "Natural Language Processing; New Research Direction"

    tag1 = Tag(workspace_id=item.workspace_id, name="Machine Learning", created_by=item.created_by)
    tag2 = Tag(workspace_id=item.workspace_id, name="Transformers", created_by=item.created_by)
    db.add_all([tag1, tag2])
    await db.flush()
    db.add(ItemTag(workspace_id=item.workspace_id, item_id=item.id, tag_id=tag2.id))
    recommendation = await db.scalar(
        select(ItemTagRecommendation).where(ItemTagRecommendation.item_id == item.id)
    )
    if recommendation is None:
        recommendation = ItemTagRecommendation(
            workspace_id=item.workspace_id,
            item_id=item.id,
            generation_token=1,
        )
        db.add(recommendation)
    recommendation.single_words = json.dumps([])
    recommendation.phrases = json.dumps(["Natural Language Processing", "New Research Direction"])
    recommendation.generated_at = datetime.now(UTC)
    await db.commit()

    organize = await client.get(f"{workspace_base}/items/{item_id}/organize")
    assert organize.status_code == 200
    assert organize.json()["tag_matrix"]["suggested_names"] == [
        "Natural Language Processing",
        "New Research Direction",
    ]

    response = await client.put(
        f"{workspace_base}/items/{item_id}/tags",
        json={
            "add_tag_ids": [tag1.id],
            "remove_tag_ids": [tag2.id],
            "new_names": [
                "Natural Language Processing",
                "New Research Direction",
                "Deep Learning",
            ],
        },
    )
    assert response.status_code == 200

    db.expire_all()
    item_tags = list(
        await db.scalars(
            select(Tag).join(ItemTag, ItemTag.tag_id == Tag.id).where(ItemTag.item_id == item_id)
        )
    )
    item_tags = [tag.name for tag in item_tags]
    assert "Machine Learning" in item_tags
    assert "Natural Language Processing" in item_tags
    assert "New Research Direction" in item_tags
    assert "Deep Learning" in item_tags
    assert "Transformers" not in item_tags
    await client.aclose()


@pytest.mark.anyio
async def test_http_api_tag_recommendation_pending_failed_and_retry_states(
    async_db, async_session_factory, tmp_path, monkeypatch, fake_durable_operations
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id
    workflow_id = f"recommendation-ui:{item.id}"
    await fake_durable_operations.enqueue(
        "library.recommend_tags",
        queue_name="library",
        workflow_id=workflow_id,
        attributes={"actor_id": item.created_by, "workspace_id": item.workspace_id},
    )
    recommendation = ItemTagRecommendation(
        workspace_id=item.workspace_id,
        item_id=item.id,
        generation_token=1,
        workflow_id=workflow_id,
        single_words=json.dumps(["stale-candidate"]),
        phrases=json.dumps([]),
    )
    db.add(recommendation)
    await db.commit()

    pending = await client.get(f"{workspace_base}/items/{item_id}/organize")
    assert pending.json()["tag_matrix"]["recommendation_state"] == "pending"
    assert pending.json()["tag_matrix"]["suggested_names"] == []

    current = fake_durable_operations.workflows[workflow_id]
    fake_durable_operations.workflows[workflow_id] = replace(
        current, state="failed", raw_status="ERROR", error="RuntimeError: extraction failed"
    )
    failed = await client.get(f"{workspace_base}/items/{item_id}/organize")
    assert failed.json()["tag_matrix"]["recommendation_state"] == "failed"
    assert failed.json()["tag_matrix"]["recommendation_error"] == (
        "RuntimeError: extraction failed"
    )

    retry = await client.post(
        f"{workspace_base}/items/{item_id}/tag-recommendations",
    )
    assert retry.status_code == 200
    retry_workflow_id = retry.json()["id"]
    assert retry_workflow_id == f"item-recommend-tags:{item_id}:2"
    progress = await client.get(f"{workspace_base}/workflows/{retry_workflow_id}")
    assert progress.json()["state"] == "pending"
    await db.refresh(recommendation)
    assert recommendation.generation_token == 2
    assert recommendation.generated_at is None
    await client.aclose()


@pytest.mark.anyio
async def test_http_api_syncs_metadata_and_updates_bibtex_key(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id

    item.title = "Temporary Title"
    item.authors = "Smith, John"
    item.publication_date = "2020-01-01"
    await db.commit()

    # Test update citation key
    response = await client.post(
        f"{workspace_base}/items/{item_id}/citation-key/regenerate",
    )
    assert response.status_code == 200
    db.expire_all()
    item = await db.get(Item, item_id)
    assert item is not None
    assert item.bibtex_id == "Smith2020Temporary"

    # Test sync metadata upstream
    mock_payload = {
        "title": "Quantum Supremacy Using a Programmable Superconducting Processor",
        "authors": "Arute, Frank; Arya, Kunal",
        "publication_title": "Nature",
        "publication_date": "2019-10-23",
        "doi": "10.1038/s41586-019-1666-5",
        "abstract": "The promise of quantum computers is that certain computational tasks might be executed exponentially faster.",
        "volume": "574",
        "issue": "7779",
        "pages": "505-510",
        "publisher": "Nature Publishing Group",
    }

    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        new=AsyncMock(
            return_value=CandidateRecord(
                provider="crossref",
                identifier=Identifier("doi", "10.1038/s41586-019-1666-5"),
                **mock_payload,
            )
        ),
    ):
        response = await client.post(
            f"{workspace_base}/items/{item_id}/metadata/sync",
            json={
                "expected_version": item.version,
                "provider": "doi",
                "uid": "10.1038/s41586-019-1666-5",
            },
        )
        assert response.status_code == 200

    db.expire_all()
    item = await db.get(Item, item_id)
    assert item is not None
    assert item.title == "Quantum Supremacy Using a Programmable Superconducting Processor"
    assert item.volume == "574"
    assert item.doi == "10.1038/s41586-019-1666-5"
    await client.aclose()


@pytest.mark.anyio
async def test_http_api_sync_metadata_uses_effective_runtime_provider_settings(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    db.add(SystemSetting(key="nasa_ads_token", value="runtime-ads-token"))
    await db.commit()

    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        new=AsyncMock(
            return_value=CandidateRecord(
                provider="nasa",
                identifier=Identifier("bibcode", "2024ApJ...123A...1X"),
                title="Runtime-configured metadata",
            )
        ),
    ) as lookup:
        response = await client.post(
            f"{workspace_base}/items/{item.id}/metadata/sync",
            json={
                "expected_version": item.version,
                "provider": "bibcode",
                "uid": "2024ApJ...123A...1X",
            },
        )

    assert response.status_code == 200
    assert lookup.call_args.args[2].nasa_ads_token == "runtime-ads-token"
    await client.aclose()


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (ValidationFailure("identifier is malformed"), 422),
        (ResourceNotFound("metadata not found"), 404),
        (UpstreamServiceError("provider unavailable"), 502),
    ],
)
@pytest.mark.anyio
async def test_http_api_sync_metadata_translates_expected_lookup_failures(
    async_db, async_session_factory, tmp_path, monkeypatch, error, status_code
):
    client, item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"

    with patch("quirebase.library.identifiers.lookup_candidate", new=AsyncMock(side_effect=error)):
        response = await client.post(
            f"{workspace_base}/items/{item.id}/metadata/sync",
            json={
                "expected_version": item.version,
                "provider": "doi",
                "uid": "invalid",
            },
        )

    assert response.status_code == status_code
    await client.aclose()


@pytest.mark.anyio
async def test_http_api_suggests_authors(async_db, async_session_factory, tmp_path, monkeypatch):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"

    a1 = Author(last_name="LeCun", first_name="Yann")
    a2 = Author(last_name="Bengio", first_name="Yoshua")
    a3 = Author(last_name="Hinton", first_name="Geoffrey")
    remote = Author(last_name="Leibniz", first_name="Gottfried")
    other = User(username="author-suggestion-other", password_hash="unused")
    db.add_all([a1, a2, a3, remote, other])
    await db.flush()
    await provision_initial_workspace(db, other)
    other_item = Item(workspace_id=fixture_workspace_id(other), title="Other", created_by=other.id)
    db.add(other_item)
    await db.flush()
    db.add_all([
        ItemAuthor(item_id=item.id, author_id=a1.id),
        ItemAuthor(item_id=other_item.id, author_id=remote.id),
    ])
    await db.commit()

    response = await client.get(f"{workspace_base}/authors?query=le")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["last_name"] == "LeCun"
    assert data[0]["first_name"] == "Yann"
    assert data[0]["id"] == a1.id

    forbidden = await client.get(
        f"/api/v1/workspaces/{fixture_workspace_id(other)}/authors?query=le"
    )
    assert forbidden.status_code == 403

    client.cookies.clear()
    assert (await client.get(f"{workspace_base}/authors?query=le")).status_code == 401
    await client.aclose()


@pytest.mark.anyio
async def test_http_api_edit_synchronizes_identifier_rows(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id
    db.add(ItemIdentifier(item_id=item.id, provider="pmid", value="old-pmid"))
    item.doi = "10.1000/old"
    item.identifiers = '{"doi": "10.1000/old", "pmid": "old-pmid"}'
    await db.commit()

    response = await client.put(
        f"{workspace_base}/items/{item_id}",
        json={
            "expected_version": item.version,
            "metadata": {
                "title": item.title,
                "doi": "https://doi.org/10.1000/new",
                "identifiers": [
                    {"provider": "doi", "value": "10.1000/stale"},
                    {"provider": "arxiv", "value": "2401.12345"},
                ],
            },
        },
    )

    assert response.status_code == 200
    db.expire_all()
    updated = await db.get(Item, item_id)
    assert updated is not None
    assert updated.doi == "10.1000/new"
    assert updated.identifiers == '{"arxiv": "2401.12345"}'
    links = list(await db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item_id)))
    assert {(link.provider, link.value) for link in links} == {
        ("arxiv", "2401.12345"),
    }
    await client.aclose()


@pytest.mark.anyio
async def test_http_api_edit_can_clear_all_structured_editors(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id
    editor = Author(last_name="Knuth", first_name="Donald")
    db.add(editor)
    await db.flush()
    db.add(ItemAuthor(item_id=item.id, author_id=editor.id, position=1, role="editor"))
    item.editors = "Knuth, Donald"
    await db.commit()

    response = await client.put(
        f"{workspace_base}/items/{item_id}",
        json={
            "expected_version": item.version,
            "metadata": {"title": item.title, "editors": []},
        },
    )

    assert response.status_code == 200
    db.expire_all()
    updated = await db.get(Item, item_id)
    assert updated is not None
    assert updated.editors is None
    assert (
        await db.scalar(
            select(func.count())
            .select_from(ItemAuthor)
            .where(ItemAuthor.item_id == item_id, ItemAuthor.role == "editor")
        )
        == 0
    )
    await client.aclose()


@pytest.mark.anyio
async def test_http_api_serializes_structured_people_as_json(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    author = Author(last_name='O"Connor & Co\\', first_name='Ada "A"')
    editor = Author(last_name="D'Angelo", first_name="Luca")
    db.add_all([author, editor])
    await db.flush()
    db.add_all([
        ItemAuthor(
            item_id=item.id,
            author_id=author.id,
            position=1,
            role="author",
            is_corresponding=True,
        ),
        ItemAuthor(
            item_id=item.id,
            author_id=editor.id,
            position=1,
            role="editor",
        ),
    ])
    await db.commit()

    response = await client.get(f"{workspace_base}/items/{item.id}")

    assert response.status_code == 200
    assert response.json()["structured_authors"] == [
        {
            "last_name": 'O"Connor & Co\\',
            "first_name": 'Ada "A"',
            "is_corresponding": True,
        }
    ]
    assert response.json()["editors"] == [
        {
            "last_name": "D'Angelo",
            "first_name": "Luca",
            "is_corresponding": False,
        }
    ]
    await client.aclose()
