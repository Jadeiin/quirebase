"""CSL-JSON projection and rendering over the citeproc engine."""

from __future__ import annotations

from typing import Any

from citeproc import Citation, CitationItem, CitationStylesBibliography, formatter
from citeproc.source.json import CiteProcJSON
from commonmeta.schema_utils import json_schema_errors

from inquiro._commonmeta_adapters import check_csl_writer_input
from inquiro.bibliography.options import BibliographyExportOptions
from inquiro.bibliography.styles import _load_style
from inquiro.richtext import convert_rich_text
from inquiro.work import contributor_suffix, work_authors, work_doi, writer_work


def _csl_names(credits: list[dict]) -> list[dict]:
    from commonmeta.utils import to_csl

    names = to_csl(credits)
    for credit, name in zip(credits, names, strict=True):
        # UPSTREAM(commonmeta-py 0.309): to_csl has no suffix projection from person.name.
        if suffix := contributor_suffix(credit):
            name["suffix"] = suffix
    return names


def work_to_csl_json(
    work: dict, options: BibliographyExportOptions | None = None, *, item_id: str | None = None
) -> dict:
    options = (options or BibliographyExportOptions()).validated(file_format="csl-json")
    return _work_to_csl_json(writer_work(work), options, item_id=item_id)


def _work_to_csl_json(
    snapshot: dict, options: BibliographyExportOptions, *, item_id: str | None = None
) -> dict:
    """Convert a prepared writer snapshot with already validated export options."""
    import json

    from commonmeta import Metadata

    check_csl_writer_input(snapshot)
    payload = Metadata(snapshot, via="commonmeta", no_network=True).write(to="csl")
    if payload is None:
        raise ValueError("Commonmeta CSL conversion returned no record")
    entry = json.loads(payload)
    doi = work_doi(snapshot)
    if doi:
        # UPSTREAM(commonmeta-py 0.309): DOI is emitted as URI-escaped text.
        # Preserve the raw DOI separately from the encoded resolver URI.
        entry["DOI"] = doi
    # UPSTREAM(commonmeta-py 0.309): its license `copyright` is not a CSL
    # property. Keep the full license in Work/Commonmeta, outside this projection.
    entry.pop("copyright", None)
    # UPSTREAM(commonmeta-py 0.309): CSL output attributes every credit as an
    # author, so project Author and Editor roles separately using its utilities.
    entry.pop("author", None)
    if authors := work_authors(snapshot):
        entry["author"] = _csl_names(authors)
    if editors := [
        credit for credit in snapshot.get("contributors", []) if "Editor" in credit.get("roles", [])
    ]:
        entry["editor"] = _csl_names(editors)
    if item_id is not None:
        entry["id"] = item_id
    if not options.include_abstract:
        entry.pop("abstract", None)
    if options.doi_policy == "omit":
        entry.pop("DOI", None)
    if not options.includes_url(has_doi=bool(doi)):
        entry.pop("URL", None)
    excluded = {field.casefold() for field in options.excluded_fields}
    entry = {field: value for field, value in entry.items() if field.casefold() not in excluded}
    if error := json_schema_errors(entry, "csl"):
        raise ValueError(
            f"Commonmeta cannot export this {snapshot['type']} Work as valid CSL-JSON: {error}; use Commonmeta"
        )
    return entry


def render_bibliography(
    csl_json: list[dict[str, Any]], style_xml: str, output_format: str = "text"
) -> list[str]:
    """Render CSL-JSON records to styled bibliography entries."""
    if not csl_json:
        return []
    # Rendering is a trust boundary: CSL strings (including nested names) can
    # contain markup. Normalize a temporary copy before citeproc interpolates
    # them, preserving identity keys and the original Work/CSL export values.
    records = [
        _rendering_value(
            {key: value for key, value in row.items() if key != "categories"},
            output_format=output_format,
        )
        for row in csl_json
    ]
    source = CiteProcJSON(records)
    style = _load_style(style_xml)
    output = formatter.html if output_format == "html" else formatter.plain
    bibliography = CitationStylesBibliography(style, source, output)
    citation = Citation([CitationItem(record["id"]) for record in records])
    bibliography.register(citation)
    if getattr(style.root, "bibliography", None) is not None:
        return ["".join(entry) for entry in bibliography.bibliography()]
    if getattr(style.root, "citation", None) is not None:
        return ["".join(bibliography.cite(citation, lambda _: None))]
    return [str(record.get("title", "")) for record in records]


def _rendering_value(value: Any, *, output_format: str) -> Any:
    if isinstance(value, str):
        return convert_rich_text(
            value, source="html", target="html" if output_format == "html" else "text"
        )
    if isinstance(value, list):
        return [_rendering_value(child, output_format=output_format) for child in value]
    if isinstance(value, dict):
        return {
            key: child if key == "id" else _rendering_value(child, output_format=output_format)
            for key, child in value.items()
        }
    return value


def render_citation(
    record: dict,
    style_xml: str,
    output_format: str = "text",
    options: BibliographyExportOptions | None = None,
) -> str:
    """Render a single record to one formatted citation."""
    entries = render_bibliography(
        [work_to_csl_json(record, options=options)], style_xml, output_format
    )
    return entries[0] if entries else ""
