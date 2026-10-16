"""Standalone upstream reproducers; no Inquiro or Quirebase imports.

These intentionally fail against unmodified commonmeta-py 0.309. Run explicitly
with pytest; they are outside the application's normal test collection.
"""

from __future__ import annotations

from copy import deepcopy

import pytest
from commonmeta import Metadata
from commonmeta.readers.csl_reader import read_csl
from commonmeta.readers.ris_reader import read_ris, ris_meta
from commonmeta.writers.csl_writer import write_csl


@pytest.mark.parametrize(
    "tag,value",
    [
        ("T1", "State-of-the-art analysis"),
        ("DO", "10.1000/foo-bar"),
        ("AU", "Jean-Pierre Smith"),
        ("AB", "A well-known result"),
        ("UR", "https://example.org/full-text"),
    ],
)
def test_ris_values_keep_hyphens(tag, value):
    assert ris_meta(f"TY  - JOUR\n{tag}  - {value}\nER  - ")[tag] == value


def test_ris_accepts_standard_title_alias():
    assert read_ris("TY  - JOUR\nTI  - Standard title\nER  - ")["title"] == "Standard title"


@pytest.mark.parametrize("source_id", ["Doe2024", "smith2024", 0, 1])
@pytest.mark.parametrize("doi", [None, "10.1000/example"])
def test_csl_record_keys_are_not_bibliographic_ids(source_id, doi):
    payload = {
        "id": source_id,
        "type": "article-journal",
        "title": "CSL record key",
        **({"DOI": doi} if doi else {}),
    }
    before = deepcopy(payload)
    result = read_csl(payload)
    if doi:
        assert result["id"] == f"https://doi.org/{doi}"
    else:
        assert result["id"].startswith("urn:uuid:")
    assert payload == before


@pytest.mark.parametrize(
    "endpoints,expected",
    [
        ([[2020, 1, 1], [2022, 5, 20]], None),
        ([[2020, 1, 1], [2020, 1, 20]], "2020-01"),
        ([[2020, 1, 1], [2020, 5, 20]], "2020"),
        ([[2020], [2020, 1, 20]], "2020"),
        ([[2020, 1], [2020, 1, 20]], "2020-01"),
    ],
)
def test_csl_date_ranges_do_not_invent_an_exact_publication_date(endpoints, expected):
    payload = {
        "id": "https://doi.org/10.1000/range",
        "type": "article-journal",
        "issued": {"date-parts": endpoints},
    }
    before = deepcopy(payload)
    assert read_csl(payload)["date_published"] == expected
    assert payload == before


def test_csl_versioned_software_keeps_software_type():
    work = {
        "id": "https://doi.org/10.1000/software",
        "type": "Software",
        "title": "Example software",
        "version": "1.0",
    }
    result = write_csl(Metadata(work, via="commonmeta", no_network=True))
    assert result["type"] == "software"
    assert result["version"] == "1.0"
