from __future__ import annotations

import asyncio
import json
from typing import Any, Self
from uuid import uuid4

import pytest
from commonmeta.author_utils import get_one_author
from commonmeta.base_utils import compact
from inquiro import ProviderRuntime
from inquiro.cli import _parser, _run, main
from inquiro.models import (
    CandidateNotFound,
    CandidatePage,
    CandidateRecord,
    Identifier,
    ProviderConfig,
    SearchQuery,
)
from inquiro.transport import MockExchange, TransportResponse
from inquiro.work import work_identifiers
from inquiro_provider_helpers import work_identifier


class FakeRuntime:
    def __init__(self, config: ProviderConfig, result: object) -> None:
        self.config = config
        self.result = result
        self.lookup_call: tuple[str, str] | None = None
        self.search_query: SearchQuery | None = None
        self.closed = False

    async def lookup(self, value: str, *, provider: str = "auto") -> object:
        self.lookup_call = (value, provider)
        return self.result

    async def search(self, query: SearchQuery) -> object:
        self.search_query = query
        return self.result

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        self.closed = True


@pytest.mark.parametrize("file_format", ["json", "bibtex"])
def test_openalex_doi_lookup_keeps_input_separate_from_returned_identities(file_format, capsys):
    payload = {
        "id": "https://openalex.org/W1230000000",
        "display_name": "Resolved Item",
        "doi": "https://doi.org/10.1000/Canonical",
    }
    exchange = MockExchange(lambda request: TransportResponse(200, json.dumps(payload).encode()))
    args = _parser().parse_args([
        "lookup",
        "10.1000/canonical",
        "--provider",
        "openalex",
        "--format",
        file_format,
    ])
    asyncio.run(_run(args, lambda config: ProviderRuntime.with_exchange(config, exchange)))
    output = capsys.readouterr().out
    if file_format == "json":
        result = json.loads(output)
        assert result["provider"] == "openalex"
        assert result["lookup_identifier"] == {"provider": "openalex", "value": "10.1000/canonical"}
        assert "identifier" not in result
        assert work_identifiers(result["work"]) == {
            ("openalex", "W1230000000"),
            ("doi", "10.1000/canonical"),
        }
    else:
        assert "doi = {10.1000/canonical}" in output
        assert "doi = {10.1000/canonical}" in output


def test_lookup_outputs_candidate_as_json_and_closes_runtime(capsys, monkeypatch):
    monkeypatch.setenv("INQUIRO_CONTACT_EMAIL", "agent@example.test")
    candidate = CandidateRecord(
        provider="crossref",
        lookup_identifier=Identifier("doi", "10.1000/example"),
        work=compact({
            "id": f"urn:uuid:{uuid4()}",
            "type": "Document",
            "title": "An example",
            "identifiers": [work_identifier("doi", "10.1000/example")],
        }),
    )
    created: list[FakeRuntime] = []

    def factory(config: ProviderConfig) -> FakeRuntime:
        runtime = FakeRuntime(config, candidate)
        created.append(runtime)
        return runtime

    args = _parser().parse_args([
        "--timeout",
        "2.5",
        "lookup",
        "10.1000/example",
        "--provider",
        "doi",
    ])
    asyncio.run(_run(args, factory))
    output = json.loads(capsys.readouterr().out)
    assert output["lookup_identifier"] == {"provider": "doi", "value": "10.1000/example"}
    assert output["work"]["title"] == "An example"
    assert created[0].lookup_call == ("10.1000/example", "doi")
    assert created[0].config.timeout_seconds == pytest.approx(2.5)
    assert created[0].config.contact_email == "agent@example.test"
    assert created[0].closed


def test_search_maps_all_options_to_one_runtime_query(capsys):
    page = CandidatePage("openalex", (), 0, 2, 5)
    created: list[FakeRuntime] = []

    def factory(config: ProviderConfig) -> FakeRuntime:
        runtime = FakeRuntime(config, page)
        created.append(runtime)
        return runtime

    args = _parser().parse_args([
        "search",
        "openalex",
        "machine learning",
        "--field",
        "title",
        "--clause",
        "author",
        "not",
        "Example",
        "--page",
        "2",
        "--per-page",
        "5",
        "--sort",
        "date",
        "--year-from",
        "2020",
        "--year-to",
        "2025",
    ])
    asyncio.run(_run(args, factory))
    assert json.loads(capsys.readouterr().out) == {
        "provider": "openalex",
        "results": [],
        "total": 0,
        "page": 2,
        "per_page": 5,
    }
    query = created[0].search_query
    assert query is not None
    assert [(clause.field, clause.operator, clause.term) for clause in query.clauses] == [
        ("title", "and", "machine learning"),
        ("author", "not", "Example"),
    ]
    assert (query.page, query.per_page, query.sort) == (2, 5, "date")
    assert (query.year_from, query.year_to) == (2020, 2025)
    assert created[0].closed


@pytest.mark.parametrize(
    ("file_format", "expected"),
    [
        ("bibtex", "@article{Doe2025Api"),
        ("ris", "TY  - JOUR"),
        ("csl-json", "article-journal"),
        ("commonmeta", "JournalArticle"),
    ],
)
def test_lookup_exports_each_bibliography_format(file_format: str, expected: str, capsys):
    candidate = CandidateRecord(
        provider="crossref",
        lookup_identifier=Identifier("doi", "10.1000/example"),
        work=compact({
            "id": "https://doi.org/10.1000/example",
            "type": "JournalArticle",
            "title": "An API Example",
            "description": "Export me",
            "date_published": "2025-04-03",
            "contributors": (
                get_one_author({"name": "Doe, Jane"}),
                get_one_author({"name": "de la Cruz, Juan"}),
            ),
            "container": {"title": "Testing Quarterly"},
            "identifiers": [
                work_identifier("doi", "10.1000/example"),
                work_identifier("openalex", "W1230000000"),
            ],
        }),
    )
    args = _parser().parse_args(["lookup", "10.1000/example", "--format", file_format])
    asyncio.run(_run(args, lambda config: FakeRuntime(config, candidate)))
    output = capsys.readouterr().out
    assert expected in output
    assert "Testing Quarterly" in output
    assert "10.1000/example" in output


def test_search_export_disambiguates_duplicate_generated_keys(capsys):
    candidates = tuple(
        CandidateRecord(
            provider="crossref",
            lookup_identifier=Identifier("doi", f"10.1000/{number}"),
            work=compact({
                "id": f"urn:uuid:{uuid4()}",
                "type": "JournalArticle",
                "title": "The Same Work",
                "date_published": "2025",
                "contributors": (get_one_author({"name": "Doe, Jane"}),),
            }),
        )
        for number in range(2)
    )
    page = CandidatePage("crossref", candidates, 2, 1, 10)
    args = _parser().parse_args([
        "search",
        "crossref",
        "same work",
        "--format",
        "bibtex",
        "--omit-abstract",
    ])
    asyncio.run(_run(args, lambda config: FakeRuntime(config, page)))
    output = capsys.readouterr().out
    assert "@article{Doe2025Same," in output
    assert "@article{Doe2025Samea," in output
    assert "title = {The Same Work}" in output


@pytest.mark.parametrize(("error", "exit_code"), [(CandidateNotFound("no result"), 3)])
def test_known_errors_are_structured_on_stderr(
    error: Exception, exit_code: int, capsys, monkeypatch
):

    class FailingRuntime(FakeRuntime):
        async def lookup(self, value: str, *, provider: str = "auto") -> Any:
            raise error

    monkeypatch.setattr("inquiro.cli.ProviderRuntime", lambda config: FailingRuntime(config, None))
    assert main(["lookup", "10.1000/missing"]) == exit_code
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {"type": "CandidateNotFound", "message": "no result"}
    }
