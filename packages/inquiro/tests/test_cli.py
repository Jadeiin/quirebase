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
