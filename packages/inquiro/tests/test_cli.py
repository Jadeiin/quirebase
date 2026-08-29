from __future__ import annotations

import json
from typing import Any, Self

import pytest
from inquiro.cli import _parser, _run, main
from inquiro.models import (
    CandidateNotFound,
    CandidatePage,
    CandidateRecord,
    Identifier,
    ProviderConfig,
    SearchQuery,
)


class FakeRuntime:
    def __init__(self, config: ProviderConfig, result: object) -> None:
        self.config = config
        self.result = result
        self.lookup_call: tuple[str, str] | None = None
        self.search_query: SearchQuery | None = None
        self.closed = False

    def lookup(self, value: str, *, provider: str = "auto") -> object:
        self.lookup_call = (value, provider)
        return self.result

    def search(self, query: SearchQuery) -> object:
        self.search_query = query
        return self.result

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.closed = True


def test_lookup_outputs_candidate_as_json_and_closes_runtime(capsys, monkeypatch):
    monkeypatch.setenv("INQUIRO_CONTACT_EMAIL", "agent@example.test")
    candidate = CandidateRecord(
        provider="crossref",
        identifier=Identifier("doi", "10.1000/example"),
        title="An example",
        identifiers=(Identifier("doi", "10.1000/example"),),
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
    _run(args, factory)

    output = json.loads(capsys.readouterr().out)
    assert output["identifier"] == {"provider": "doi", "value": "10.1000/example"}
    assert output["title"] == "An example"
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
    _run(args, factory)

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
        ("biblatex", "@article{Doe2025Api"),
        ("ris", "TY  - JOUR"),
        ("endnote", "%0 Journal Article"),
    ],
)
def test_lookup_exports_each_bibliography_format(
    file_format: str,
    expected: str,
    capsys,
):
    candidate = CandidateRecord(
        provider="crossref",
        identifier=Identifier("doi", "10.1000/example"),
        title="An API Example",
        abstract="Export me",
        authors="Doe, Jane; de la Cruz, Juan",
        publication_date="2025-04-03",
        publication_title="Testing Quarterly",
        doi="10.1000/example",
        urls="https://example.test/article",
        identifiers=(
            Identifier("doi", "10.1000/example"),
            Identifier("openalex", "W123"),
        ),
        reference_type="article",
    )

    args = _parser().parse_args([
        "lookup",
        "10.1000/example",
        "--format",
        file_format,
        "--include-identifiers",
    ])
    _run(args, lambda config: FakeRuntime(config, candidate))

    output = capsys.readouterr().out
    assert expected in output
    assert "Testing Quarterly" in output
    assert "10.1000/example" in output
    if file_format in {"bibtex", "biblatex"}:
        assert "openalex = {W123}" in output


def test_search_export_disambiguates_duplicate_generated_keys(capsys):
    candidates = tuple(
        CandidateRecord(
            provider="crossref",
            identifier=Identifier("doi", f"10.1000/{number}"),
            title="The Same Work",
            authors="Doe, Jane",
            publication_date="2025",
            reference_type="article",
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
        "--preserve-case",
    ])

    _run(args, lambda config: FakeRuntime(config, page))

    output = capsys.readouterr().out
    assert "@article{Doe2025Same," in output
    assert "@article{Doe2025Samea," in output
    assert "title = {{T}he {S}ame {W}ork}" in output


@pytest.mark.parametrize(
    ("error", "exit_code"),
    [(CandidateNotFound("no result"), 3)],
)
def test_known_errors_are_structured_on_stderr(
    error: Exception,
    exit_code: int,
    capsys,
    monkeypatch,
):
    class FailingRuntime(FakeRuntime):
        def lookup(self, value: str, *, provider: str = "auto") -> Any:
            raise error

    monkeypatch.setattr("inquiro.cli.ProviderRuntime", lambda config: FailingRuntime(config, None))

    assert main(["lookup", "10.1000/missing"]) == exit_code
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "error": {"type": "CandidateNotFound", "message": "no result"}
    }
