"""The Citation Key formula DSL: evaluation, disambiguation suffixes and preview."""

from __future__ import annotations

import re
import unicodedata

from inquiro.richtext import convert_rich_text
from inquiro.work import work_authors

DEFAULT_CITATION_KEY_FORMULA = "auth.capitalize + year + shorttitle(1).capitalize"

_FORMULA_FIELD = re.compile(
    r"^(auth|year|title|journal|type|authors\(\d+\)|shorttitle\(\d+\))"
    r"((?:\.(?:lower|upper|capitalize|fold|alphanum|truncate\(\d+\)))*)$"
)
_FORMULA_OPERATION = re.compile(r"\.(lower|upper|capitalize|fold|alphanum|truncate\((\d+)\))")
_YEAR_PATTERN = re.compile(r"\b(19\d\d|20\d\d)\b")
_STOP_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


class CitationKeyFormulaError(ValueError):
    """The Citation Key formula is outside Inquiro's deliberately small DSL."""


def extract_year(publication_date: str | None) -> str | None:
    match = _YEAR_PATTERN.search(publication_date or "")
    return match.group(1) if match else None


def generate_default_citation_key(item: dict, *, max_length: int = 255) -> str:
    author_part = "Unknown"
    if work_authors(item):
        last_name = _author_family(work_authors(item)[0])
        # Clean non-alphanumeric
        last_clean = re.sub(r"[^A-Za-z0-9]", "", last_name)
        if last_clean:
            author_part = last_clean.capitalize()

    year_part = extract_year(item.get("date_published")) or "XXXX"

    title_part = "Work"
    if item.get("title"):
        plain_title = convert_rich_text(item.get("title", ""), source="html", target="text")
        words = re.findall(r"[A-Za-z0-9]+", plain_title)
        for word in words:
            if word.lower() not in _STOP_WORDS and len(word) > 2:
                title_part = word.capitalize()
                break

    # Reserve room for both the year and title even when the family name is long.
    author_part = author_part[: max_length // 2]
    title_part = title_part[: max_length - len(author_part) - len(year_part)]
    return f"{author_part}{year_part}{title_part}"


def _split_formula(formula: str) -> list[str]:
    parts: list[str] = []
    start = 0
    quote: str | None = None
    escaped = False
    for position, character in enumerate(formula):
        if escaped:
            escaped = False
        elif character == "\\" and quote:
            escaped = True
        elif character in {'"', "'"}:
            quote = None if quote == character else character if quote is None else quote
        elif character == "+" and quote is None:
            parts.append(formula[start:position].strip())
            start = position + 1
    if quote:
        raise CitationKeyFormulaError("unterminated string literal")
    parts.append(formula[start:].strip())
    if any(not part for part in parts):
        raise CitationKeyFormulaError("formula terms must be separated by '+'")
    return parts


def citation_key_suffix(position: int) -> str:
    suffix = ""
    while position:
        position, remainder = divmod(position - 1, 26)
        suffix = chr(ord("a") + remainder) + suffix
    return suffix


def suffixed_citation_key(key: str, position: int, *, max_length: int = 255) -> str:
    """Append a collision suffix while keeping the complete key within its limit."""
    suffix = citation_key_suffix(position)
    if len(suffix) >= max_length:
        return suffix[-max_length:]
    return f"{key[: max_length - len(suffix)]}{suffix}"


def _fold(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


def _formula_count(value: str) -> int:
    if not value.isdigit() or len(value) > 4:
        raise CitationKeyFormulaError("numeric formula arguments must have at most four digits")
    count = int(value)
    if count < 1:
        raise CitationKeyFormulaError("numeric formula arguments must be positive")
    return count


def _formula_value(record: dict, field_name: str) -> str:
    if field_name == "auth":
        return _author_family(work_authors(record)[0]) if work_authors(record) else "Unknown"
    if field_name.startswith("authors("):
        count = _formula_count(field_name[8:-1])
        return (
            "".join(_author_family(author) for author in work_authors(record)[:count]) or "Unknown"
        )
    if field_name == "year":
        return extract_year(record.get("date_published")) or "XXXX"
    if field_name == "title":
        return convert_rich_text(record.get("title", ""), source="html", target="text") or "Work"
    if field_name.startswith("shorttitle("):
        count = _formula_count(field_name[11:-1])
        plain_title = convert_rich_text(record.get("title", ""), source="html", target="text")
        words = re.findall(r"[^\W_]+", plain_title, flags=re.UNICODE)
        significant = [word for word in words if word.casefold() not in _STOP_WORDS]
        return "".join((significant or words)[:count]) or "Work"
    if field_name == "journal":
        return record.get("container", {}).get("title") or ""
    if field_name == "type":
        return record.get("type", "Other")
    raise CitationKeyFormulaError(f"unknown field: {field_name}")


def evaluate_citation_key_formula(
    formula: str,
    record: dict,
    *,
    force_ascii: bool = False,
    max_length: int = 255,
) -> str:
    if not formula.strip():
        raise CitationKeyFormulaError("formula is required")
    output: list[str] = []
    for term in _split_formula(formula.strip()):
        if term[0] in {'"', "'"}:
            import ast

            try:
                literal = ast.literal_eval(term)
            except (SyntaxError, ValueError) as error:
                raise CitationKeyFormulaError("invalid string literal") from error
            if not isinstance(literal, str):
                raise CitationKeyFormulaError("only string literals are allowed")
            output.append(literal)
            continue
        match = _FORMULA_FIELD.fullmatch(term)
        if match is None:
            raise CitationKeyFormulaError(f"invalid formula term: {term}")
        value = _formula_value(record, match.group(1))
        for operation in _FORMULA_OPERATION.finditer(match.group(2)):
            name = operation.group(1)
            if name == "lower":
                value = value.lower()
            elif name == "upper":
                value = value.upper()
            elif name == "capitalize":
                value = value[:1].upper() + value[1:].lower()
            elif name == "fold":
                value = _fold(value)
            elif name == "alphanum":
                value = "".join(character for character in value if character.isalnum())
            elif name.startswith("truncate"):
                try:
                    count = _formula_count(operation.group(2) or "")
                except CitationKeyFormulaError as error:
                    raise CitationKeyFormulaError("truncate requires a positive count") from error
                value = value[:count]
        output.append(value)
    result = "".join(output)
    if force_ascii:
        result = _fold(result).encode("ascii", "ignore").decode("ascii")
    result = "".join(
        character for character in result if character.isalnum() or character in "_:-."
    )
    return (result or "UnknownXXXXWork")[:max_length]


def _author_family(contributor: dict) -> str:
    entity = contributor.get(contributor["type"].lower(), {})
    return entity.get("family_name") or entity.get("name") or "Unknown"


_PREVIEW_SAMPLE = {
    "id": "urn:uuid:cf281c3d-c96f-4ce6-a6f1-17460c42e79b",
    "type": "JournalArticle",
    "title": "A Sketch of the Analytical Engine",
    "contributors": [
        {
            "type": "Person",
            "person": {"family_name": "Lovelace", "given_name": "Ada"},
            "roles": ["Author"],
        }
    ],
    "date_published": "1843",
    "container": {"title": "Scientific Memoirs"},
}


def validate_citation_key_formula(formula: str) -> None:
    """Validate formula syntax without applying it to a caller's record."""
    evaluate_citation_key_formula(formula, _PREVIEW_SAMPLE)


def preview_citation_key(formula: str, *, force_ascii: bool = False) -> str:
    """Render a formula over a sample record pair, showing the collision suffix.

    Returns ``"key  keya"``: the sample and a near-duplicate evaluated with the
    formula, with the export disambiguation suffix applied on collision.
    """
    duplicate = _PREVIEW_SAMPLE | {"title": "A Sketch of the Analytical Engine (revisited)"}
    keys = [
        evaluate_citation_key_formula(formula, record, force_ascii=force_ascii)
        for record in (_PREVIEW_SAMPLE, duplicate)
    ]
    if keys[1].casefold() == keys[0].casefold():
        keys[1] = f"{keys[1]}{citation_key_suffix(1)}"
    return "  ".join(keys)
