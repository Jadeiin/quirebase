from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, Protocol, Self, TextIO

from inquiro.bibliography import (
    DEFAULT_CITATION_KEY_FORMULA,
    BibliographyExportOptions,
    BibliographyRecord,
    Contributor,
    evaluate_citation_key_formula,
    export_bibliography_records,
    suffixed_citation_key,
)
from inquiro.models import (
    CandidateNotFound,
    CandidatePage,
    CandidateRecord,
    InquiroError,
    InvalidProviderRequest,
    ProviderConfig,
    ProviderUnavailable,
    SearchClause,
    SearchQuery,
)
from inquiro.runtime import ProviderRuntime

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType


class Runtime(Protocol):
    def lookup(self, value: str, *, provider: str = "auto") -> CandidateRecord: ...

    def search(self, query: SearchQuery) -> CandidatePage: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...


class RuntimeFactory(Protocol):
    def __call__(self, config: ProviderConfig) -> Runtime: ...


OUTPUT_FORMATS = ("json", "bibtex", "biblatex", "ris", "endnote")


def _add_output_options(command: argparse.ArgumentParser) -> None:
    command.add_argument(
        "--format",
        choices=OUTPUT_FORMATS,
        default="json",
        dest="output_format",
        help="Output format (default: json).",
    )
    command.add_argument(
        "--encoding",
        choices=("unicode", "latex"),
        default="unicode",
        help="BibTeX/BibLaTeX text encoding (default: unicode).",
    )
    command.add_argument(
        "--preserve-case",
        action="store_true",
        help="Protect uppercase title text in BibTeX/BibLaTeX output.",
    )
    command.add_argument(
        "--omit-abstract",
        action="store_true",
        help="Omit abstracts from bibliography output.",
    )
    command.add_argument(
        "--include-identifiers",
        action="store_true",
        help="Include identifiers in addition to DOI.",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inquiro",
        description="Look up, discover, and export scholarly Candidate Records.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        metavar="SECONDS",
        help="Provider request timeout (default: 10).",
    )
    parser.add_argument(
        "--max-response-bytes",
        type=int,
        default=10_000_000,
        metavar="BYTES",
        help="Maximum provider response size (default: 10000000).",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    lookup = commands.add_parser("lookup", help="Look up one Candidate Record by identifier.")
    lookup.add_argument("identifier", help="DOI, ISBN, PMID, arXiv ID, or provider identifier.")
    lookup.add_argument(
        "--provider",
        default="auto",
        help="Identifier provider or auto detection (default: auto).",
    )
    _add_output_options(lookup)

    search = commands.add_parser("search", help="Search one scholarly metadata provider.")
    search.add_argument("provider", help="Search provider, such as crossref or openalex.")
    search.add_argument("term", help="Search term for the first clause.")
    search.add_argument(
        "--field",
        choices=("any", "title", "author", "publication", "abstract"),
        default="any",
        help="Field for the first clause (default: any).",
    )
    search.add_argument(
        "--operator",
        choices=("and", "or", "not"),
        default="and",
        help="Operator for the first clause (default: and).",
    )
    search.add_argument(
        "--clause",
        action="append",
        default=[],
        nargs=3,
        metavar=("FIELD", "OPERATOR", "TERM"),
        help="Add a field/operator/term clause; may be repeated.",
    )
    search.add_argument("--page", type=int, default=1)
    search.add_argument("--per-page", type=int, default=10)
    search.add_argument("--sort", default="relevance")
    search.add_argument("--year-from", type=int)
    search.add_argument("--year-to", type=int)
    _add_output_options(search)
    return parser


def _provider_config(args: argparse.Namespace) -> ProviderConfig:
    return ProviderConfig(
        timeout_seconds=args.timeout,
        max_response_bytes=args.max_response_bytes,
        contact_email=os.environ.get("INQUIRO_CONTACT_EMAIL"),
        openalex_api_key=os.environ.get("INQUIRO_OPENALEX_API_KEY"),
        ncbi_api_key=os.environ.get("INQUIRO_NCBI_API_KEY"),
        nasa_ads_token=os.environ.get("INQUIRO_NASA_ADS_TOKEN"),
        ieee_api_key=os.environ.get("INQUIRO_IEEE_API_KEY"),
    )


def _search_query(args: argparse.Namespace) -> SearchQuery:
    clauses = [SearchClause(args.field, args.operator, args.term)]
    clauses.extend(SearchClause(field, operator, term) for field, operator, term in args.clause)
    return SearchQuery(
        provider=args.provider,
        clauses=tuple(clauses),
        page=args.page,
        per_page=args.per_page,
        sort=args.sort,
        year_from=args.year_from,
        year_to=args.year_to,
    )


def _write_json(value: object, *, stream: TextIO | None = None) -> None:
    stream = stream or sys.stdout
    json.dump(value, stream, ensure_ascii=False, indent=2)
    stream.write("\n")


def _candidate_contributors(value: str | None) -> tuple[Contributor, ...]:
    return tuple(
        Contributor.parse(part.strip()) for part in (value or "").split(";") if part.strip()
    )


def _candidate_record(candidate: CandidateRecord) -> BibliographyRecord:
    identifiers = tuple(
        (identifier.provider, identifier.value)
        for identifier in candidate.identifiers
        if identifier.provider.casefold() != "doi"
    )
    record = BibliographyRecord(
        citation_key=None,
        reference_type=candidate.reference_type or "article",
        title=candidate.title,
        authors=_candidate_contributors(candidate.authors),
        abstract=candidate.abstract,
        keywords=tuple(
            keyword.strip() for keyword in (candidate.keywords or "").split(";") if keyword.strip()
        ),
        publication_date=candidate.publication_date,
        publication_title=candidate.publication_title,
        journal_abbreviation=candidate.journal_abbreviation,
        volume=candidate.volume,
        issue=candidate.issue,
        pages=candidate.pages,
        publisher=candidate.publisher,
        doi=candidate.doi,
        urls=tuple(url.strip() for url in (candidate.urls or "").splitlines() if url.strip()),
        identifiers=identifiers,
    )
    return replace(
        record,
        citation_key=evaluate_citation_key_formula(
            DEFAULT_CITATION_KEY_FORMULA,
            record,
            force_ascii=True,
        ),
    )


def _bibliography_records(candidates: Sequence[CandidateRecord]) -> list[BibliographyRecord]:
    records: list[BibliographyRecord] = []
    used: set[str] = set()
    for candidate in candidates:
        record = _candidate_record(candidate)
        base = record.citation_key or "UnknownXXXXWork"
        key = base
        position = 1
        while unicodedata.normalize("NFKC", key).casefold() in used:
            key = suffixed_citation_key(base, position)
            position += 1
        used.add(unicodedata.normalize("NFKC", key).casefold())
        records.append(replace(record, citation_key=key))
    return records


def _write_result(result: CandidateRecord | CandidatePage, args: argparse.Namespace) -> None:
    if args.output_format == "json":
        _write_json(asdict(result))
        return
    candidates = (result,) if isinstance(result, CandidateRecord) else result.results
    options = BibliographyExportOptions(
        include_abstract=not args.omit_abstract,
        preserve_case=args.preserve_case,
        encoding=args.encoding,
        include_identifiers=args.include_identifiers,
    )
    sys.stdout.write(
        export_bibliography_records(
            _bibliography_records(candidates),
            args.output_format,
            options=options,
        )
    )


def _run(args: argparse.Namespace, runtime_factory: RuntimeFactory) -> None:
    with runtime_factory(_provider_config(args)) as runtime:
        result: CandidateRecord | CandidatePage
        if args.command == "lookup":
            result = runtime.lookup(args.identifier, provider=args.provider)
        else:
            result = runtime.search(_search_query(args))
    _write_result(result, args)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _run(args, ProviderRuntime)
    except InquiroError as error:
        _write_json(
            {"error": {"type": type(error).__name__, "message": str(error)}},
            stream=sys.stderr,
        )
        if isinstance(error, InvalidProviderRequest):
            return 2
        if isinstance(error, CandidateNotFound):
            return 3
        if isinstance(error, ProviderUnavailable):
            return 4
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
