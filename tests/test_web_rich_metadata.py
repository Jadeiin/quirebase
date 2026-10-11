from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from app_helpers import json_payload
from inquiro import CandidateRecord, Contributor, Identifier
from item_helpers import contributor_values, metadata_list_values, stored_doi
from sqlalchemy import select
from test_http import authenticated_async_client
from workspace_helpers import fixture_workspace_id, provision_initial_workspace

from quirebase.core.errors import ResourceNotFound, UpstreamServiceError, ValidationFailure
from quirebase.models import (
    Item,
    ItemIdentifier,
    ItemTag,
    ItemTagRecommendation,
    SystemSetting,
    Tag,
    User,
)


@pytest.mark.anyio
async def test_citation_key_preview_is_an_authenticated_account_capability(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    client, _item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.get(
            "/api/v1/account/citation-key-preview", params={"formula": "auth + year"}
        )
        assert response.status_code == 200
        assert response.json()["key"]
        invalid = await client.get(
            "/api/v1/account/citation-key-preview", params={"formula": "broken("}
        )
        assert invalid.status_code == 422
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fields",
    [
        {"reference_type": "journal-article"},
        {"reference_type": "unrecognized"},
        {"publication_date": "2023-02-29"},
        {"publication_date": "Spring 2024"},
    ],
)
async def test_http_metadata_rejects_unsupported_types_and_invalid_dates(
    async_db, async_session_factory, tmp_path, monkeypatch, fields
):
    client, item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    try:
        response = await client.post(
            f"/api/v1/workspaces/{item.workspace_id}/items", json={"title": "Rejected", **fields}
        )
        assert response.status_code == 422
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["authors", "editors"])
@pytest.mark.parametrize("operation", ["create", "update"])
async def test_http_metadata_rejects_duplicates_after_name_normalization(
    async_db, async_session_factory, tmp_path, monkeypatch, role, operation
):
    client, item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{item.workspace_id}/items"
    original_title, original_version = item.title, item.version
    metadata = {
        "title": "Duplicate credits",
        role: [
            {"display_name": "John Smith", "family_name": " "},
            {"display_name": "John Smith"},
        ],
    }
    try:
        if operation == "create":
            response = await client.post(base, json=metadata)
        else:
            response = await client.put(
                f"{base}/{item.id}",
                json={"expected_version": original_version, "metadata": metadata},
            )

        assert response.status_code == 422
        assert await async_db.scalar(select(Item).where(Item.title == metadata["title"])) is None
        await async_db.refresh(item)
        assert item.title == original_title and item.version == original_version
    finally:
        await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("role", ["authors", "editors"])
async def test_http_normalized_contributor_metadata_can_be_read_and_saved_again(
    async_db, async_session_factory, tmp_path, monkeypatch, role
):
    client, item, _ = await authenticated_async_client(
        async_db, async_session_factory, tmp_path, monkeypatch
    )
    base = f"/api/v1/workspaces/{item.workspace_id}/items"
    try:
        created = await client.post(
            base,
            json={
                "title": "Distinct suffixes",
                role: [
                    {
                        "display_name": " John  Smith ",
                        "family_name": " ",
                        "given_name": "\t",
                        "suffix": suffix,
                    }
                    for suffix in (" Jr ", " Sr ")
                ],
            },
        )
        assert created.status_code == 201
        item_url = f"{base}/{created.json()['id']}"
        read = await client.get(item_url)
        assert read.status_code == 200
        original = read.json()
        credits = original["metadata"][role]
        assert [credit["display_name"] for credit in credits] == ["John Smith", "John Smith"]
        assert all(
            credit["family_name"] is None and credit["given_name"] is None for credit in credits
        )
        assert [credit["suffix"] for credit in credits] == ["Jr", "Sr"]

        for title in (original["metadata"]["title"], "Title-only change"):
            metadata = original["metadata"] | {"title": title}
            updated = await client.put(
                item_url,
                json={"expected_version": original["version"], "metadata": metadata},
            )
            assert updated.status_code == 200
            read = await client.get(item_url)
            assert read.status_code == 200
            original = read.json()
            assert original["metadata"] == metadata
            assert original["metadata"][role] == credits
    finally:
        await client.aclose()


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
        json=json_payload({
            "title": "Complete manual record",
            "abstract": "All editable metadata is accepted during creation.",
            "reference_type": "article",
            "publication_date": "2026-08-17",
            "publication_title": "Journal of Complete Forms",
            "journal_abbreviation": "JCF",
            "volume": "12",
            "issue": "3",
            "pages": "10-20",
            "publisher": "Example Press",
            "place_published": "Shanghai",
            "doi": "https://doi.org/10.1000/complete",
            "citation_key": "complete2026record",
            "urls": [{"url": "https://example.test/record"}, {"url": "https://example.test/pdf"}],
            "keywords": ["forms", "metadata"],
            "identifiers": [{"provider": "pmid", "value": "12345"}],
            "custom_fields": [{"name": "rating", "value": 5}],
            "authors": [
                {
                    "display_name": "Lovelace, Ada",
                    "family_name": "Lovelace",
                    "given_name": "Ada",
                    "is_corresponding": True,
                },
                {
                    "display_name": "Turing, Alan",
                    "family_name": "Turing",
                    "given_name": "Alan",
                },
            ],
            "editors": [
                {
                    "display_name": "Hopper, Grace",
                    "family_name": "Hopper",
                    "given_name": "Grace",
                }
            ],
        }),
    )

    assert response.status_code == 201
    created = await db.scalar(select(Item).where(Item.title == "Complete manual record"))
    assert created is not None
    assert response.json() == json_payload({"id": created.id, "version": 1})
    assert created.authors == [
        {
            "display_name": "Lovelace, Ada",
            "family_name": "Lovelace",
            "given_name": "Ada",
            "is_corresponding": True,
        },
        {
            "display_name": "Turing, Alan",
            "family_name": "Turing",
            "given_name": "Alan",
            "is_corresponding": None,
        },
    ]
    assert created.editors == contributor_values("Hopper, Grace", is_corresponding=None)
    assert (await stored_doi(db, created)) == "10.1000/complete"
    assert {
        row.provider: row.value
        for row in await db.scalars(
            select(ItemIdentifier).where(ItemIdentifier.item_id == created.id)
        )
    } == {"doi": "10.1000/complete", "pmid": "12345"}
    assert created.keywords == metadata_list_values("forms; metadata")
    assert created.urls == metadata_list_values(
        "https://example.test/record\nhttps://example.test/pdf", urls=True
    )
    assert (created.custom_fields or {}) == {"rating": 5}
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
        json=json_payload({
            "expected_version": item.version,
            "metadata": {
                "title": "Attention Is All You Need",
                "abstract": "The dominant sequence transduction models are based on complex recurrent networks.",
                "reference_type": "paper-conference",
                "publication_date": "2017-06-12",
                "publication_title": "Advances in Neural Information Processing Systems",
                "journal_abbreviation": "NeurIPS",
                "volume": "30",
                "issue": "1",
                "pages": "5998-6008",
                "publisher": "Curran Associates, Inc.",
                "place_published": "Long Beach, CA",
                "doi": "10.5555/3295222.3295349",
                "citation_key": "vaswani2017attention",
                "urls": [
                    {"url": "https://arxiv.org/abs/1706.03762"},
                    {"url": "https://proceedings.neurips.cc/paper/7181"},
                ],
                "custom_fields": [
                    {"name": "rating", "value": 5},
                    {"name": "flags", "value": ["reviewed"]},
                    {"name": "meta", "value": {"source": "manual"}},
                ],
                "authors": [
                    {
                        "display_name": "Vaswani, Ashish",
                        "family_name": "Vaswani",
                        "given_name": "Ashish",
                        "is_corresponding": True,
                    },
                    {
                        "display_name": "Shazeer, Noam",
                        "family_name": "Shazeer",
                        "given_name": "Noam",
                    },
                    {
                        "display_name": "Parmar, Niki",
                        "family_name": "Parmar",
                        "given_name": "Niki",
                    },
                ],
                "editors": [
                    {
                        "display_name": "Guyon, Isabelle",
                        "family_name": "Guyon",
                        "given_name": "Isabelle",
                    },
                    {
                        "display_name": "von Luxburg, Ulrike",
                        "family_name": "von Luxburg",
                        "given_name": "Ulrike",
                    },
                ],
            },
        }),
    )
    assert response.status_code == 200

    db.expire_all()
    updated = await db.get(Item, item_id)
    assert updated is not None
    assert updated.title == "Attention Is All You Need"
    assert updated.journal_abbreviation == "NeurIPS"
    assert updated.volume == "30"
    assert updated.pages == "5998-6008"
    assert updated.citation_key == "vaswani2017attention"
    assert (updated.custom_fields or {}) == {
        "rating": 5,
        "flags": ["reviewed"],
        "meta": {"source": "manual"},
    }
    assert updated.updated_by is not None
    assert [row["family_name"] for row in updated.authors] == ["Vaswani", "Shazeer", "Parmar"]
    assert updated.editors == contributor_values(
        "Guyon, Isabelle; von Luxburg, Ulrike", is_corresponding=None
    )

    assert len(updated.authors) == 3
    assert updated.authors[0]["is_corresponding"] is True
    assert updated.authors[1]["is_corresponding"] is None
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
    item.keywords = metadata_list_values("Natural Language Processing; New Research Direction")

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
    recommendation.single_words = []
    recommendation.phrases = ["Natural Language Processing", "New Research Direction"]
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
        json=json_payload({
            "add_tag_ids": [tag1.id],
            "remove_tag_ids": [tag2.id],
            "new_names": [
                "Natural Language Processing",
                "New Research Direction",
                "Deep Learning",
            ],
        }),
    )
    assert response.status_code == 200

    organized = await client.get(f"{workspace_base}/items/{item_id}/organize")
    assert organized.status_code == 200
    selected_tags = {tag["name"] for tag in organized.json()["tags"]}
    assert selected_tags == {
        "Machine Learning",
        "Natural Language Processing",
        "New Research Direction",
        "Deep Learning",
    }
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
        single_words=["stale-candidate"],
        phrases=[],
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
async def test_http_api_syncs_metadata_and_updates_citation_key(
    async_db, async_session_factory, tmp_path, monkeypatch
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id

    item.title = "Temporary Title"
    item.authors = contributor_values("Smith, John")
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
    assert item.citation_key == "Smith2020Temporary"

    # Test sync metadata upstream
    mock_payload = {
        "title": "Quantum Supremacy Using a Programmable Superconducting Processor",
        "authors": (Contributor("Arute, Frank"), Contributor("Arya, Kunal")),
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
                lookup_identifier=Identifier("doi", "10.1038/s41586-019-1666-5"),
                identifiers=(Identifier("doi", mock_payload["doi"]),),
                **{key: value for key, value in mock_payload.items() if key != "doi"},
            )
        ),
    ):
        response = await client.post(
            f"{workspace_base}/items/{item_id}/metadata/sync",
            json=json_payload({
                "expected_version": item.version,
                "provider": "doi",
                "uid": "10.1038/s41586-019-1666-5",
            }),
        )
        assert response.status_code == 200

    db.expire_all()
    item = await db.get(Item, item_id)
    assert item is not None
    assert item.title == "Quantum Supremacy Using a Programmable Superconducting Processor"
    assert item.volume == "574"
    assert (await stored_doi(db, item)) == "10.1038/s41586-019-1666-5"
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
                provider="nasa_ads",
                lookup_identifier=Identifier("bibcode", "2024ApJ...123A...1X"),
                title="Runtime-configured metadata",
            )
        ),
    ) as lookup:
        response = await client.post(
            f"{workspace_base}/items/{item.id}/metadata/sync",
            json=json_payload({
                "expected_version": item.version,
                "provider": "bibcode",
                "uid": "2024ApJ...123A...1X",
            }),
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
            json=json_payload({
                "expected_version": item.version,
                "provider": "doi",
                "uid": "invalid",
            }),
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

    other = User(username="author-suggestion-other", password_hash="unused")
    db.add(other)
    await db.flush()
    await provision_initial_workspace(db, other)
    other_item = Item(
        workspace_id=fixture_workspace_id(other),
        title="Other",
        created_by=other.id,
        authors=contributor_values("Leibniz, Gottfried"),
    )
    db.add(other_item)
    item.authors = contributor_values("LeCun, Yann")
    await db.commit()

    response = await client.get(f"{workspace_base}/authors?query=le")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["last_name"] == "LeCun"
    assert data[0]["first_name"] == "Yann"
    assert "id" not in data[0]

    forbidden = await client.get(
        f"/api/v1/workspaces/{fixture_workspace_id(other)}/authors?query=le"
    )
    assert forbidden.status_code == 404
    assert forbidden.json() == {
        "code": "workspace_unavailable",
        "message": "Workspace not found",
    }

    client.cookies.clear()
    assert (await client.get(f"{workspace_base}/authors?query=le")).status_code == 401
    await client.aclose()


@pytest.mark.anyio
@pytest.mark.parametrize("include_doi_alias", [False, True], ids=["identifiers-only", "doi-alias"])
async def test_http_api_edit_synchronizes_identifier_rows(
    async_db, async_session_factory, tmp_path, monkeypatch, include_doi_alias
):
    db = async_db
    client, item, _ = await authenticated_async_client(
        db, async_session_factory, tmp_path, monkeypatch
    )
    workspace_base = f"/api/v1/workspaces/{item.workspace_id}"
    item_id = item.id
    db.add(
        ItemIdentifier(
            workspace_id=item.workspace_id, item_id=item.id, provider="pmid", value="old-pmid"
        )
    )
    db.add(
        ItemIdentifier(
            workspace_id=item.workspace_id, item_id=item.id, provider="doi", value="10.1000/old"
        )
    )
    await db.commit()

    response = await client.put(
        f"{workspace_base}/items/{item_id}",
        json=json_payload({
            "expected_version": item.version,
            "metadata": {
                "title": item.title,
                **({"doi": "https://doi.org/10.1000/new"} if include_doi_alias else {}),
                "identifiers": [
                    {"provider": "doi", "value": "10.1000/NEW"},
                    {"provider": "arxiv", "value": "2401.12345"},
                ],
            },
        }),
    )

    assert response.status_code == 200
    db.expire_all()
    updated = await db.get(Item, item_id)
    assert updated is not None
    assert (await stored_doi(db, updated)) == "10.1000/new"
    links = list(await db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item_id)))
    assert {(link.provider, link.value) for link in links} == {
        ("doi", "10.1000/new"),
        ("arxiv", "2401.12345"),
    }
    response = await client.put(
        f"{workspace_base}/items/{item_id}",
        json=json_payload({
            "expected_version": updated.version,
            "metadata": {
                "title": updated.title,
                "identifiers": [{"provider": "arxiv", "value": "2401.12345"}],
            },
        }),
    )
    assert response.status_code == 200
    db.expire_all()
    updated = await db.get(Item, item_id)
    assert (await stored_doi(db, updated)) is None
    links = list(await db.scalars(select(ItemIdentifier).where(ItemIdentifier.item_id == item_id)))
    assert [(link.provider, link.value) for link in links] == [("arxiv", "2401.12345")]
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
    item.editors = contributor_values("Knuth, Donald")
    await db.commit()

    response = await client.put(
        f"{workspace_base}/items/{item_id}",
        json=json_payload({
            "expected_version": item.version,
            "metadata": {"title": item.title, "editors": []},
        }),
    )

    assert response.status_code == 200
    db.expire_all()
    updated = await db.get(Item, item_id)
    assert updated is not None
    assert updated.editors == []
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
    item.authors = [
        {
            "display_name": 'O"Connor & Co\\, Ada "A"',
            "family_name": 'O"Connor & Co\\',
            "given_name": 'Ada "A"',
            "is_corresponding": True,
            "kind": "unknown",
            "identifiers": [],
            "affiliations": None,
            "suffix": None,
        }
    ]
    item.editors = contributor_values("D'Angelo, Luca")
    await db.commit()

    response = await client.get(f"{workspace_base}/items/{item.id}")

    assert response.status_code == 200
    assert response.json()["structured_authors"] == [
        {
            "display_name": 'O"Connor & Co\\, Ada "A"',
            "family_name": 'O"Connor & Co\\',
            "given_name": 'Ada "A"',
            "is_corresponding": True,
            "kind": "unknown",
            "identifiers": [],
            "affiliations": None,
            "suffix": None,
        }
    ]
    assert response.json()["editors"] == [
        {
            "display_name": "D'Angelo, Luca",
            "family_name": "D'Angelo",
            "given_name": "Luca",
            "is_corresponding": False,
            "kind": "unknown",
            "identifiers": [],
            "affiliations": None,
            "suffix": None,
        }
    ]
    await client.aclose()
