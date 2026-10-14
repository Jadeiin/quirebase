from __future__ import annotations

import json
import runpy
from pathlib import Path
from uuid import uuid4

import inquiro
from commonmeta.author_utils import get_one_author
from commonmeta.base_utils import compact
from inquiro import CandidateRecord, Identifier
from item_helpers import work_identifier


def test_metadata_diagnostic_script_reports_lookup_inputs_and_structured_authors(
    monkeypatch, capsys
):
    contributor = get_one_author({
        "name": "Juan de la Cruz",
        "familyName": "de la Cruz",
        "givenName": "Juan",
    })
    requests = []

    class Runtime:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            pass

        async def lookup(self, value, *, provider):
            requests.append((provider, value))
            source = {"doi": "crossref", "pmid": "pubmed", "arxiv": "arxiv"}[provider]
            return CandidateRecord(
                provider=source,
                lookup_identifier=Identifier(provider, value),
                work=compact({
                    "id": f"urn:uuid:{uuid4()}",
                    "type": "Document",
                    "title": "Structured metadata",
                    "contributors": (contributor,),
                    "identifiers": [work_identifier(provider, value)],
                }),
            )

    monkeypatch.setattr(inquiro, "ProviderRuntime", Runtime)
    script = Path(__file__).resolve().parents[1] / "scripts" / "check-metadata-providers.py"
    runpy.run_path(str(script), run_name="__main__")
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(records) == len(requests) == 4
    assert records[0]["provider"] == "crossref"
    for record, (namespace, value) in zip(records, requests, strict=True):
        assert record["lookup_identifier"] == {"provider": namespace, "value": value}
        assert record["work"]["identifiers"] == [work_identifier(namespace, value)]
        author = record["work"]["contributors"][0]["person"]
        assert (author["family_name"], author["given_name"]) == ("de la Cruz", "Juan")
