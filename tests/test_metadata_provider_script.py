from __future__ import annotations

import json
import runpy
from pathlib import Path

import inquiro
from inquiro import Affiliation, CandidateRecord, Contributor, Identifier


def test_metadata_diagnostic_script_reports_lookup_inputs_and_structured_authors(
    monkeypatch, capsys
):
    contributor = Contributor(
        display_name="Juan de la Cruz",
        family_name="de la Cruz",
        given_name="Juan",
        kind="person",
        identifiers=(Identifier("orcid", "0000-0002-1825-0097"),),
        affiliations=(Affiliation("研究所", identifiers=(Identifier("ror", "03yrm5c26"),)),),
    )
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
                title="Structured metadata",
                authors=(contributor,),
                identifiers=(Identifier(provider, value),),
            )

    monkeypatch.setattr(inquiro, "ProviderRuntime", Runtime)
    script = Path(__file__).resolve().parents[1] / "scripts" / "check-metadata-providers.py"
    runpy.run_path(str(script), run_name="__main__")

    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(records) == len(requests) == 4
    assert records[0]["provider"] == "crossref"
    for record, (namespace, value) in zip(records, requests, strict=True):
        assert record["lookup_identifier"] == {"provider": namespace, "value": value}
        assert record["identifiers"] == [{"provider": namespace, "value": value}]
        author = record["authors"][0]
        assert author["display_name"] == "Juan de la Cruz"
        assert (author["family_name"], author["given_name"]) == ("de la Cruz", "Juan")
        assert author["identifiers"] == [{"provider": "orcid", "value": "0000-0002-1825-0097"}]
        assert author["affiliations"][0]["name"] == "研究所"
        assert author["affiliations"][0]["identifiers"] == [
            {"provider": "ror", "value": "03yrm5c26"}
        ]
