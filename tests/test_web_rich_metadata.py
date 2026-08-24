from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from inquiro import CandidateRecord, Identifier
from test_http import authenticated_client

from quirebase.core.errors import ResourceNotFound, UpstreamServiceError, ValidationFailure
from quirebase.models import (
    Author,
    Item,
    ItemAuthor,
    ItemIdentifier,
    ItemTag,
    ItemTagRecommendation,
    Job,
    JobState,
    SystemSetting,
    Tag,
)


def test_web_new_item_exposes_and_saves_complete_metadata(db, tmp_path, monkeypatch):
    client, _item, _ = authenticated_client(db, tmp_path, monkeypatch)

    page = client.get("/bibliography/import")
    assert page.status_code == 200
    assert 'data-method="manual"' in page.text
    for field in (
        "title",
        "author_last_name[]",
        "editor_last_name[]",
        "reference_type",
        "publication_date",
        "publication_title",
        "journal_abbreviation",
        "volume",
        "issue",
        "pages",
        "affiliation",
        "publisher",
        "place_published",
        "doi",
        "bibtex_id",
        "bibtex_type",
        "urls",
        "keywords",
        "abstract",
        "identifiers",
        "custom_fields",
    ):
        assert f'name="{field}"' in page.text

    response = client.post(
        "/items?csrf_token=test-csrf",
        data={
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
            "bibtex_id": "complete2026record",
            "bibtex_type": "article",
            "urls": "https://example.test/record\nhttps://example.test/pdf",
            "keywords": "forms; metadata",
            "identifiers": '{"pmid": "12345"}',
            "custom_fields": '{"rating": 5}',
            "author_last_name[]": ["Lovelace", "Turing"],
            "author_first_name[]": ["Ada", "Alan"],
            "author_is_corr[]": ["0"],
            "editor_last_name[]": ["Hopper"],
            "editor_first_name[]": ["Grace"],
            "structured_editors_present": "true",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    created = db.query(Item).filter_by(title="Complete manual record").one()
    assert response.headers["location"] == f"/items/{created.id}"
    assert created.authors == "Lovelace, Ada; Turing, Alan"
    assert created.editors == "Hopper, Grace"
    assert created.doi == "10.1000/complete"
    assert json.loads(created.identifiers or "") == {"pmid": "12345"}
    assert created.keywords == "forms; metadata"
    assert created.urls == "https://example.test/record\nhttps://example.test/pdf"
    assert json.loads(created.custom_fields or "") == {"rating": 5}


def test_web_edit_rich_metadata_and_structured_authors(db, tmp_path, monkeypatch):
    client, item, _ = authenticated_client(db, tmp_path, monkeypatch)
    csrf = "test-csrf"

    response = client.post(
        f"/items/{item.id}/edit",
        params={"csrf_token": csrf},
        data={
            "version": item.version,
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
            "bibtex_id": "vaswani2017attention",
            "bibtex_type": "inproceedings",
            "urls": "https://arxiv.org/abs/1706.03762\nhttps://proceedings.neurips.cc/paper/7181",
            "custom_fields": '{"rating": 5, "flags": ["reviewed"], "meta": {"source": "manual"}}',
            "author_last_name[]": ["Vaswani", "Shazeer", "Parmar"],
            "author_first_name[]": ["Ashish", "Noam", "Niki"],
            "author_is_corr[]": ["0"],
            "editor_last_name[]": ["Guyon", "von Luxburg"],
            "editor_first_name[]": ["Isabelle", "Ulrike"],
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    db.expire_all()
    updated = db.get(Item, item.id)
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
    authors = (
        db
        .query(ItemAuthor)
        .filter_by(item_id=item.id, role="author")
        .order_by(ItemAuthor.position)
        .all()
    )
    assert len(authors) == 3
    assert authors[0].is_corresponding is True
    assert authors[1].is_corresponding is False


def test_web_tag_matrix_batch_and_selection(db, tmp_path, monkeypatch):
    client, item, _ = authenticated_client(db, tmp_path, monkeypatch)
    csrf = "test-csrf"
    item.keywords = "Natural Language Processing; New Research Direction"

    tag1 = Tag(name="Machine Learning", created_by=item.created_by)
    tag2 = Tag(name="Transformers", created_by=item.created_by)
    db.add_all([tag1, tag2])
    recommendation = db.query(ItemTagRecommendation).filter_by(item_id=item.id).one_or_none()
    if recommendation is None:
        recommendation = ItemTagRecommendation(
            item_id=item.id,
            input_fingerprint="b" * 64,
            generation_token=1,
            engine="yake",
            engine_version="0.7.3",
        )
        db.add(recommendation)
    recommendation.single_words = json.dumps([])
    recommendation.phrases = json.dumps(["Natural Language Processing", "New Research Direction"])
    recommendation.generated_at = datetime.now(UTC)
    db.commit()

    organize = client.get(f"/items/{item.id}/organize")
    assert organize.status_code == 200
    assert "New Research Direction" in organize.text
    assert 'name="suggested_tags" value="New Research Direction"' in organize.text

    # Submit matrix form with selected tag1 and newly added tags
    response = client.post(
        f"/items/{item.id}/tags/matrix",
        params={"csrf_token": csrf},
        data={
            "tag_ids": [tag1.id],
            "suggested_tags": ["Natural Language Processing", "New Research Direction"],
            "new_tags": "Deep Learning",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    db.expire_all()
    item_tags = [
        t.name
        for t in db
        .query(Tag)
        .join(ItemTag, ItemTag.tag_id == Tag.id)
        .filter(ItemTag.item_id == item.id)
        .all()
    ]
    assert "Machine Learning" in item_tags
    assert "Natural Language Processing" in item_tags
    assert "New Research Direction" in item_tags
    assert "Deep Learning" in item_tags
    assert "Transformers" not in item_tags


def test_web_tag_recommendation_pending_failed_and_retry_states(db, tmp_path, monkeypatch):
    client, item, _ = authenticated_client(db, tmp_path, monkeypatch)
    job = Job(
        kind="item.recommend_tags",
        payload="{}",
        idempotency_key=f"recommendation-ui:{item.id}",
        owner_id=item.created_by,
    )
    db.add(job)
    db.flush()
    recommendation = ItemTagRecommendation(
        item_id=item.id,
        input_fingerprint="c" * 64,
        generation_token=1,
        job_id=job.id,
        engine="yake",
        engine_version="0.7.3",
        single_words=json.dumps(["stale-candidate"]),
        phrases=json.dumps([]),
    )
    db.add(recommendation)
    db.commit()

    pending = client.get(f"/items/{item.id}/organize")
    assert "正在生成标签推荐" in pending.text
    assert "stale-candidate" not in pending.text
    assert pending.text.index("tag-recommendation-action") < pending.text.index(
        'class="metadata-form"'
    )

    job.state = JobState.failed
    job.error = "RuntimeError: extraction failed"
    db.commit()
    failed = client.get(f"/items/{item.id}/organize")
    assert "标签推荐生成失败" in failed.text
    assert "extraction failed" in failed.text
    assert "重试推荐" in failed.text

    retry = client.post(
        f"/items/{item.id}/tag-recommendations",
        params={"csrf_token": "test-csrf"},
        follow_redirects=False,
    )
    assert retry.status_code == 303
    db.refresh(recommendation)
    assert recommendation.generation_token == 2
    assert recommendation.generated_at is None


def test_web_sync_metadata_and_bibtex_key_update(db, tmp_path, monkeypatch):
    client, item, _ = authenticated_client(db, tmp_path, monkeypatch)
    csrf = "test-csrf"

    item.title = "Temporary Title"
    item.authors = "Smith, John"
    item.publication_date = "2020-01-01"
    db.commit()

    # Test update citation key
    response = client.post(
        f"/items/{item.id}/update-bibtex-key",
        params={"csrf_token": csrf},
        data={"version": item.version},
        follow_redirects=True,
    )
    assert response.status_code == 200
    db.expire_all()
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
        return_value=CandidateRecord(
            provider="crossref",
            identifier=Identifier("doi", "10.1038/s41586-019-1666-5"),
            **mock_payload,
        ),
    ):
        response = client.post(
            f"/items/{item.id}/sync-metadata",
            params={"csrf_token": csrf},
            data={
                "version": item.version,
                "provider": "doi",
                "uid": "10.1038/s41586-019-1666-5",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200

    db.expire_all()
    assert item.title == "Quantum Supremacy Using a Programmable Superconducting Processor"
    assert item.volume == "574"
    assert item.doi == "10.1038/s41586-019-1666-5"


def test_web_sync_metadata_uses_effective_runtime_provider_settings(db, tmp_path, monkeypatch):
    client, item, _ = authenticated_client(db, tmp_path, monkeypatch)
    db.add(SystemSetting(key="nasa_ads_token", value="runtime-ads-token"))
    db.commit()

    with patch(
        "quirebase.library.identifiers.lookup_candidate",
        return_value=CandidateRecord(
            provider="nasa",
            identifier=Identifier("bibcode", "2024ApJ...123A...1X"),
            title="Runtime-configured metadata",
        ),
    ) as lookup:
        response = client.post(
            f"/items/{item.id}/sync-metadata?csrf_token=test-csrf",
            data={
                "version": item.version,
                "provider": "bibcode",
                "uid": "2024ApJ...123A...1X",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    assert lookup.call_args.args[2].nasa_ads_token == "runtime-ads-token"


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (ValidationFailure("identifier is malformed"), 422),
        (ResourceNotFound("metadata not found"), 404),
        (UpstreamServiceError("provider unavailable"), 502),
    ],
)
def test_web_sync_metadata_translates_expected_lookup_failures(
    db, tmp_path, monkeypatch, error, status_code
):
    client, item, _ = authenticated_client(db, tmp_path, monkeypatch)

    with patch("quirebase.library.identifiers.lookup_candidate", side_effect=error):
        response = client.post(
            f"/items/{item.id}/sync-metadata?csrf_token=test-csrf",
            data={"version": item.version, "provider": "doi", "uid": "invalid"},
            follow_redirects=False,
        )

    assert response.status_code == status_code


def test_web_author_suggest_api(db, tmp_path, monkeypatch):
    client, _, _ = authenticated_client(db, tmp_path, monkeypatch)

    a1 = Author(last_name="LeCun", first_name="Yann")
    a2 = Author(last_name="Bengio", first_name="Yoshua")
    a3 = Author(last_name="Hinton", first_name="Geoffrey")
    db.add_all([a1, a2, a3])
    db.commit()

    response = client.get("/api/authors/suggest?q=le")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["last_name"] == "LeCun"
    assert data[0]["first_name"] == "Yann"

    client.cookies.clear()
    assert client.get("/api/authors/suggest?q=le").status_code == 401


def test_web_edit_synchronizes_identifier_rows(db, tmp_path, monkeypatch):
    client, item, _ = authenticated_client(db, tmp_path, monkeypatch)
    db.add(ItemIdentifier(item_id=item.id, provider="pmid", value="old-pmid"))
    item.doi = "10.1000/old"
    item.identifiers = '{"doi": "10.1000/old", "pmid": "old-pmid"}'
    db.commit()

    response = client.post(
        f"/items/{item.id}/edit?csrf_token=test-csrf",
        data={
            "version": item.version,
            "title": item.title,
            "doi": "https://doi.org/10.1000/new",
            "identifiers": '{"doi": "10.1000/stale", "arxiv": "2401.12345"}',
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db.expire_all()
    updated = db.get(Item, item.id)
    assert updated.doi == "10.1000/new"
    assert updated.identifiers == '{"arxiv": "2401.12345"}'
    links = db.query(ItemIdentifier).filter_by(item_id=item.id).all()
    assert {(link.provider, link.value) for link in links} == {
        ("arxiv", "2401.12345"),
    }


def test_web_edit_can_clear_all_structured_editors(db, tmp_path, monkeypatch):
    client, item, _ = authenticated_client(db, tmp_path, monkeypatch)
    editor = Author(last_name="Knuth", first_name="Donald")
    db.add(editor)
    db.flush()
    db.add(ItemAuthor(item_id=item.id, author_id=editor.id, position=1, role="editor"))
    item.editors = "Knuth, Donald"
    db.commit()

    response = client.post(
        f"/items/{item.id}/edit?csrf_token=test-csrf",
        data={
            "version": item.version,
            "title": item.title,
            "structured_editors_present": "true",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db.expire_all()
    assert db.get(Item, item.id).editors is None
    assert db.query(ItemAuthor).filter_by(item_id=item.id, role="editor").count() == 0


def test_metadata_editor_serializes_structured_people_as_json(db, tmp_path, monkeypatch):
    client, item, _ = authenticated_client(db, tmp_path, monkeypatch)
    author = Author(last_name='O"Connor & Co\\', first_name='Ada "A"')
    editor = Author(last_name="D'Angelo", first_name="Luca")
    db.add_all([author, editor])
    db.flush()
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
    db.commit()

    response = client.get(f"/items/{item.id}/metadata")

    assert response.status_code == 200
    assert "data-initial-authors=" in response.text
    assert 'O\\"Connor \\u0026 Co\\\\' in response.text
    assert "data-initial-editors=" in response.text
    assert "D\\u0027Angelo" in response.text
