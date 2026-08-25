from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from typing import TYPE_CHECKING, Protocol, Self, TextIO

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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inquiro",
        description="Look up and discover scholarly Candidate Records.",
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


def _run(args: argparse.Namespace, runtime_factory: RuntimeFactory) -> None:
    with runtime_factory(_provider_config(args)) as runtime:
        result: CandidateRecord | CandidatePage
        if args.command == "lookup":
            result = runtime.lookup(args.identifier, provider=args.provider)
        else:
            result = runtime.search(_search_query(args))
    _write_json(asdict(result))


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
