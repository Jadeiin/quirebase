from __future__ import annotations

import asyncio
import json

import pytest
from inquiro import ProviderRuntime
from inquiro.cli import _parser, _run, main
from inquiro.transport import HttpExchange, TransportResponse


@pytest.mark.parametrize("empty_license", [False, True])
def test_cli_lookup_with_environment_socks_proxy(monkeypatch, capsys, empty_license):
    monkeypatch.setenv("HTTPS_PROXY", "socks5://127.0.0.1:1080")

    async def source(self, request):
        await asyncio.sleep(0)
        return TransportResponse(
            200,
            json.dumps({
                "message": {
                    "DOI": "10.1016/j.engappai.2025.112079",
                    "title": ["Engineering applications"],
                    "type": "journal-article",
                    **({"license": []} if empty_license else {}),
                }
            }).encode(),
            headers={"content-type": "application/json"},
        )

    monkeypatch.setattr(HttpExchange, "send", source)
    arguments = _parser().parse_args(["lookup", "10.1016/j.engappai.2025.112079"])
    asyncio.run(_run(arguments, ProviderRuntime))
    result = json.loads(capsys.readouterr().out)
    assert result["work"]["id"] == "https://doi.org/10.1016/j.engappai.2025.112079"
    assert result["work"]["title"] == "Engineering applications"


def test_cli_unsupported_csl_type_returns_structured_error(monkeypatch, capsys):
    async def source(self, request):
        await asyncio.sleep(0)
        return TransportResponse(
            200,
            json.dumps({
                "message": {
                    "DOI": "10.1234/conference",
                    "title": ["Conference paper"],
                    "type": "proceedings-article",
                }
            }).encode(),
            headers={"content-type": "application/json"},
        )

    monkeypatch.setattr(HttpExchange, "send", source)
    assert main(["lookup", "10.1234/conference", "--format", "csl-json"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    error = json.loads(captured.err)["error"]
    assert error["type"] == "InvalidProviderRequest"
    assert "CSL" in error["message"]


def test_cli_bibtex_export_projects_rich_titles_and_organization_authors(monkeypatch, capsys):
    import bibtexparser

    async def source(self, request):
        await asyncio.sleep(0)
        return TransportResponse(
            200,
            json.dumps({
                "message": {
                    "DOI": "10.1234/safe",
                    "title": ["<i>50%</i> in R&amp;D"],
                    "type": "journal-article",
                    "author": [{"name": "Research and Development Corp."}],
                }
            }).encode(),
            headers={"content-type": "application/json"},
        )

    monkeypatch.setattr(HttpExchange, "send", source)
    assert main(["lookup", "10.1234/safe", "--format", "bibtex"]) == 0
    output = capsys.readouterr()
    assert not output.err
    entry = bibtexparser.loads(output.out).entries[0]
    assert entry["author"] == "{Research and Development Corp.}"
    assert entry["title"] == r"\textit{50\%} in R\&D"


def test_cli_bibtex_export_accepts_presentation_preferences(monkeypatch, capsys):
    import bibtexparser

    async def source(self, request):
        await asyncio.sleep(0)
        return TransportResponse(
            200,
            json.dumps({
                "message": {
                    "DOI": "10.1234/options",
                    "URL": "https://example.org/article",
                    "title": ["DNA café"],
                    "type": "journal-article",
                    "abstract": "Abstract",
                    "publisher": "Publisher",
                }
            }).encode(),
            headers={"content-type": "application/json"},
        )

    monkeypatch.setattr(HttpExchange, "send", source)
    assert (
        main([
            "lookup",
            "10.1234/options",
            "--format",
            "bibtex",
            "--encoding",
            "latex",
            "--preserve-case",
            "--doi-policy",
            "omit",
            "--url-policy",
            "omit",
            "--exclude-field",
            "abstract",
            "--exclude-field",
            "publisher",
            "--sort-by",
            "author",
        ])
        == 0
    )
    captured = capsys.readouterr()
    assert not captured.err
    entry = bibtexparser.loads(captured.out).entries[0]
    assert entry["title"].startswith("{DNA") and "café" not in entry["title"]
    assert not {"doi", "url", "abstract", "publisher"}.intersection(entry)


def test_cli_commonmeta_provider_uses_commonmeta_output_without_conversion(monkeypatch, capsys):
    snapshot = {
        "id": "https://doi.org/10.1000/example",
        "type": "Dataset",
        "title": "Example",
        "date_published": "2026-01-02T12:34:56Z",
    }

    async def source(self, request):
        await asyncio.sleep(0)
        assert request.url == "https://commonmeta.org/10.1000%2Fexample"
        assert request.params == {"format": "commonmeta"}
        return TransportResponse(200, json.dumps(snapshot).encode())

    monkeypatch.setattr(HttpExchange, "send", source)
    assert (
        main([
            "lookup",
            "https://doi.org/10.1000/example",
            "--provider",
            "commonmeta",
            "--format",
            "commonmeta",
        ])
        == 0
    )
    captured = capsys.readouterr()
    assert not captured.err
    assert json.loads(captured.out) == [snapshot]
