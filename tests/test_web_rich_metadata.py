from __future__ import annotations

from unittest.mock import patch

from test_http import authenticated_client

from quirebase.models import Author, Item, ItemAuthor, ItemTag, Tag


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
            "author_last_name": ["Vaswani", "Shazeer", "Parmar"],
            "author_first_name": ["Ashish", "Noam", "Niki"],
            "author_is_corr": ["0"],
            "editor_last_name": ["Guyon", "von Luxburg"],
            "editor_first_name": ["Isabelle", "Ulrike"],
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

    tag1 = Tag(name="Machine Learning", created_by=item.created_by)
    tag2 = Tag(name="Transformers", created_by=item.created_by)
    db.add_all([tag1, tag2])
    db.commit()

    # Submit matrix form with selected tag1 and newly added tags
    response = client.post(
        f"/items/{item.id}/tags/matrix",
        params={"csrf_token": csrf},
        data={
            "tag_ids": [tag1.id],
            "new_tags": "Natural Language Processing\nDeep Learning",
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
    assert "Deep Learning" in item_tags
    assert "Transformers" not in item_tags


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
        "quirebase.library.identifiers.lookup_metadata",
        return_value=("doi", mock_payload),
    ):
        response = client.post(
            f"/items/{item.id}/sync-metadata",
            params={"csrf_token": csrf},
            data={"provider": "doi", "uid": "10.1038/s41586-019-1666-5"},
            follow_redirects=True,
        )
        assert response.status_code == 200

    db.expire_all()
    assert item.title == "Quantum Supremacy Using a Programmable Superconducting Processor"
    assert item.volume == "574"
    assert item.doi == "10.1038/s41586-019-1666-5"


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
